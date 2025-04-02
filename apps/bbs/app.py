from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from flask_socketio import join_room as join_room_io
import uuid
import json
from sqlalchemy.orm import joinedload
from apps.bbs.gpt_api import Gpt_api

api = Gpt_api()


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
socketio = SocketIO(app)  # WebSocket を追加

# ルーム情報のテーブル
class Room(db.Model):
    id = db.Column(db.String(8), primary_key=True)
    topic = db.Column(db.String(200), nullable=False)
    criteria = db.Column(db.String(200), nullable=False)
    phase = db.Column(db.String(20), default='waiting')
    round = db.Column(db.Integer, default=1)  # ← 現在のラウンド数 (1 or 2)

# 参加者情報のテーブル
class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    room_id = db.Column(db.String(8), db.ForeignKey('room.id'), nullable=False)
    is_ready = db.Column(db.Boolean, default=False)  # ← 追加！
    has_resubmitted = db.Column(db.Boolean, default=False)  # ←追加！

# アイデアのテーブル
class Idea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    room_id = db.Column(db.String(8), db.ForeignKey('room.id'), nullable=False)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    round = db.Column(db.Integer, default=1)  # 提出ラウンドを記録

#フィードバックのテーブル
class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    to_idea_id = db.Column(db.Integer, db.ForeignKey('idea.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)

class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    idea_id = db.Column(db.Integer, db.ForeignKey('idea.id'), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    scores = db.Column(db.Text, nullable=False)
    advice = db.Column(db.Text)  # ←追加！

with app.app_context():
    db.create_all()

# ホーム画面
@app.route('/')
def home():
    return render_template('home.html')

# ルーム作成
@app.route('/create_room', methods=['GET', 'POST'])
def create_room():
    if request.method == 'POST':
        name = request.form.get('name')
        topic = request.form.get('topic')
        criteria_list = request.form.getlist('criteria')  # 複数取得！

        room_id = str(uuid.uuid4())[:8]
        criteria_json = json.dumps(criteria_list, ensure_ascii=False)  # JSON文字列で保存

        new_room = Room(id=room_id, topic=topic, criteria=criteria_json)
        db.session.add(new_room)
        db.session.commit()

        host_participant = Participant(name=name, room_id=room_id, is_ready=True)
        db.session.add(host_participant)
        db.session.commit()

        return redirect(url_for('room', room_id=room_id, participant_id=host_participant.id))

    return render_template('create_room.html')

# ルーム待機画面
@app.route('/room/<room_id>')
def room(room_id):
    room = Room.query.get(room_id)
    participants = Participant.query.filter_by(room_id=room_id).all()
    participant_id = request.args.get("participant_id")
    submitted = request.args.get("submitted")
    criteria_list = json.loads(room.criteria)
    my_idea = None
    feedback_target = None
    evaluation_result = None
    feedback_progress = None
    
      # フェーズに応じて current_phase を割り当てる
    # ラウンド1 と 2 でフェーズ順を明示的に分ける
    if room.round == 1:
        phase_order = {
            "waiting": 1,
            "brainstorming": 2,
            "feedback": 3,
            'evaluating': 3,
            "evaluated": 4,
            "rebrainstorming": 5,
            "final_result": 7
        }
    elif room.round == 2:
        phase_order = {
            "waiting": 1,
            "brainstorming": 2,
            "feedback": 6,
            'evaluating': 6,
            "evaluated": 4,
            "rebrainstorming": 5,
            "final_result": 7
        }


    current_phase = phase_order.get(room.phase, 1)
    total_phase = 7
    progress_pct = round((current_phase / total_phase) * 100.48, 2)
    
    ready_participants = sum(p.is_ready for p in participants[1:])
    all_ready = ready_participants >= 1  # ホスト以外に1人以上が準備完了ならTrue

    if participant_id:
        my_idea_obj = Idea.query.filter_by(room_id=room_id, participant_id=participant_id).first()
        if my_idea_obj:
            my_idea = my_idea_obj.content

        if room.phase == "feedback":
            subq = db.session.query(Feedback.to_idea_id).filter_by(from_participant_id=participant_id)
            feedback_target = Idea.query.filter(
                Idea.room_id == room_id,
                Idea.participant_id != int(participant_id),
                ~Idea.id.in_(subq)
            ).first()

            total_targets = Idea.query.filter(
                Idea.room_id == room_id,
                Idea.participant_id != int(participant_id)
            ).count()

            done_count = Feedback.query.join(Idea).filter(
                Feedback.from_participant_id == participant_id,
                Idea.room_id == room_id,
                Feedback.to_idea_id == Idea.id
            ).count()

            feedback_progress = {"done": done_count, "total": total_targets}

        elif room.phase == "evaluated":
            idea = Idea.query.filter_by(room_id=room_id, participant_id=participant_id).first()
            if idea:
                evaluation = Evaluation.query.filter_by(idea_id=idea.id).first()
                if evaluation:
                    evaluation_result = {
                        "summary": evaluation.summary,
                        "scores": json.loads(evaluation.scores),
                        "advice": evaluation.advice 

                    }
        
        elif room.phase == "rebrainstorming":
            idea = Idea.query.filter_by(room_id=room_id, participant_id=participant_id).first()
            if idea:
                evaluation = Evaluation.query.filter_by(idea_id=idea.id).first()
                if evaluation:
                    evaluation_result = {
                        "summary": evaluation.summary,
                        "scores": json.loads(evaluation.scores),
                        "advice": evaluation.advice 
                    }
        elif room.phase == "final_result":
            ideas = Idea.query.filter_by(room_id=room_id, round=2).all()
            evaluations = [Evaluation.query.filter_by(idea_id=idea.id).first() for idea in ideas]

            avg_scores = [
                (idea, eval, sum(json.loads(eval.scores).values()) / len(json.loads(eval.scores)))
                for idea, eval in zip(ideas, evaluations)
            ]

            max_avg = max(avg for _, _, avg in avg_scores)

            final_results = [
                {"idea": idea.content, "summary": eval.summary, "scores": json.loads(eval.scores), "advice": eval.advice}
                for idea, eval, avg in avg_scores if avg == max_avg
            ]

            return render_template(
                'room.html',
                room=room,
                participants=participants,
                self_id=participant_id,
                final_results=final_results,
                criteria_list=criteria_list,
                 current_phase=current_phase,
                total_phase=total_phase,
                progress_pct=progress_pct
            )

    return render_template(
        'room.html',
        room=room,
        participants=participants,
        self_id=participant_id,
        criteria_list=criteria_list,
        submitted=submitted,
        my_idea=my_idea,
        feedback_target=feedback_target,
        feedback_progress=feedback_progress,
        evaluation_result=evaluation_result,
        all_ready=all_ready,
        current_phase=current_phase,
        total_phase=total_phase,
        progress_pct=progress_pct
    )
# 参加者の入室
@app.route('/join_room', methods=['GET', 'POST'])
def join_room():
    if request.method == 'POST':
        room_id = request.form.get('room_id')
        name = request.form.get('name')

        room = Room.query.get(room_id)
        if not room:
            return redirect(url_for("join_room", error=1))

        new_participant = Participant(name=name, room_id=room_id)
        db.session.add(new_participant)
        db.session.commit()

        # SocketIO 通知
        socketio.emit('update_participants', {
            'room_id': room_id,
            'name': name,
            'participant_id': new_participant.id
        }, room=room_id)

        # ここで自分の参加者IDをリダイレクト先に含める
        return redirect(url_for('room', room_id=room_id, participant_id=new_participant.id))

    return render_template('join_room.html')

# WebSocket: 参加者をルームに追加
@socketio.on('join')
def handle_join(data):
    room_id = data['room_id']
    join_room_io(room_id)

# ルーム削除
@app.route('/delete_room/<room_id>', methods=['POST'])
def delete_room(room_id):
    room = Room.query.get(room_id)
    if room:
        Participant.query.filter_by(room_id=room_id).delete()
        db.session.delete(room)
        db.session.commit()

        # 🔔 全参加者に通知
        socketio.emit('room_deleted', {'room_id': room_id}, room=room_id)

    return redirect(url_for('home'))

# 参加者の退出
@app.route('/leave_room/<participant_id>', methods=['POST'])
def leave_room(participant_id):
    participant = Participant.query.get(participant_id)
    if participant:
        room_id = participant.room_id
        db.session.delete(participant)
        db.session.commit()

        # WebSocketで更新
        socketio.emit('remove_participant', {'room_id': room_id, 'participant_id': participant_id}, room=room_id)

    return redirect(url_for('home'))

@socketio.on('toggle_ready')
def handle_toggle_ready(data):
    participant_id = int(data['participant_id'])
    room_id = data['room_id']

    participants = Participant.query.filter_by(room_id=room_id).order_by(Participant.id).all()
    host_id = participants[0].id if participants else None

    # ホストは無視
    if participant_id == host_id:
        return

    participant = Participant.query.get(participant_id)
    if participant:
        participant.is_ready = not participant.is_ready
        db.session.commit()

        # 参加者全体の状態を送信
        all_participants = Participant.query.filter_by(room_id=room_id).all()
        ready_status = [
            {"id": p.id, "name": p.name, "is_ready": p.is_ready}
            for p in all_participants
        ]
        socketio.emit('update_ready_status', {
            "room_id": room_id,
            "participants": ready_status
        }, room=room_id)

@app.route('/start_brainstorming/<room_id>', methods=['POST'])
def start_brainstorming(room_id):
    room = Room.query.get(room_id)
    if room:
        room.phase = 'brainstorming'
        db.session.commit()

        # SocketIOで参加者全体に通知
        socketio.emit('phase_update', {'room_id': room_id, 'phase': 'brainstorming'}, room=room_id)

    # 👇 ホスト自身の画面もフェーズを反映するためリダイレクトさせる！
    participant_id = request.args.get("participant_id")
    return redirect(url_for('room', room_id=room_id, participant_id=participant_id))

@app.route('/submit_idea', methods=['POST'])
def submit_idea():
    participant_id = int(request.form.get('participant_id'))
    room_id = request.form.get('room_id')
    content = request.form.get('idea')

    room = Room.query.get(room_id)
    participant = Participant.query.get(participant_id)

    existing_idea = Idea.query.filter_by(room_id=room_id, participant_id=participant_id).first()
    if existing_idea:
        existing_idea.content = content
        existing_idea.round = room.round  # ラウンドを更新
    else:
        new_idea = Idea(content=content, room_id=room_id, participant_id=participant_id, round=room.round)
        db.session.add(new_idea)

    if room.phase == 'rebrainstorming':
        participant.has_resubmitted = True

    db.session.commit()

    participant_count = Participant.query.filter_by(room_id=room_id).count()

    if room.phase in ['brainstorming', 'rebrainstorming']:
        idea_count = Idea.query.filter_by(room_id=room_id, round=room.round).count()
        all_submitted = participant_count == idea_count
        next_phase = 'feedback'

        if all_submitted and room.phase == 'rebrainstorming':
            Feedback.query.filter(
                Feedback.to_idea_id.in_(
                    db.session.query(Idea.id).filter_by(room_id=room_id, round=room.round)
                )
            ).delete(synchronize_session=False)

    if all_submitted:
        room.phase = next_phase
        db.session.commit()
        socketio.emit('phase_update', {'room_id': room_id, 'phase': room.phase}, room=room_id)

    return redirect(url_for('room', room_id=room_id, participant_id=participant_id, submitted=1))

# ダミーGPT API関数を追加
def call_gpt_api(idea, feedbacks, criteria_list):
    return api.summerize(idea, feedbacks, criteria_list)
    #return {
    #    "要約": f"このアイデアに対して {len(feedbacks)} 件のフィードバックがありました。",
    #    "評価": [{c: 3 for c in criteria_list}]
    #}

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    room_id = request.form.get('room_id')
    from_id = int(request.form.get('from_participant_id'))
    to_idea_id = int(request.form.get('to_idea_id'))
    content = request.form.get('content')

    db.session.add(Feedback(from_participant_id=from_id, to_idea_id=to_idea_id, content=content))
    db.session.commit()

    room = Room.query.get(room_id)

    current_ideas = Idea.query.filter_by(room_id=room_id, round=room.round).all()
    participants = Participant.query.filter_by(room_id=room_id).all()
    expected_total = len(current_ideas) * (len(participants) - 1)
    written_total = Feedback.query.filter(Feedback.to_idea_id.in_([i.id for i in current_ideas])).count()

    if written_total >= expected_total:
        room = Room.query.get(room_id)
        room.phase = 'evaluating'
        db.session.commit()
        socketio.emit('phase_update', {'room_id': room_id, 'phase': 'evaluating'}, room=room_id)

        criteria_list = json.loads(room.criteria)

        for idea in current_ideas:
            feedbacks = Feedback.query.filter_by(to_idea_id=idea.id).all()
            feedback_texts = [f.content for f in feedbacks]

            evaluation_result = call_gpt_api(idea.content, feedback_texts, criteria_list)

             # ここで「既存の評価結果」を取得して上書き
            evaluation = Evaluation.query.filter_by(idea_id=idea.id).first()
            if evaluation:
                # 上書きする
                evaluation.summary = evaluation_result["要約"]
                evaluation.scores = json.dumps(evaluation_result["評価"][0], ensure_ascii=False)
                evaluation.advice = evaluation_result["アドバイス"]  # ←追加
            else:
                # まだない場合は新しく作る
                evaluation = Evaluation(
                    idea_id=idea.id,
                    summary=evaluation_result["要約"],
                    scores=json.dumps(evaluation_result["評価"][0], ensure_ascii=False),
                    advice = evaluation_result["アドバイス"]   # ←追加
                )
                db.session.add(evaluation)

        db.session.commit()

        if room.round == 1:
            room.phase = 'evaluated'
            
            participants = Participant.query.filter_by(room_id=room_id).all()
            for idx, p in enumerate(participants):
                if idx != 0:  # 先頭がホストと仮定
                    p.is_ready = False
                    
        elif room.round == 2:
            room.phase = 'final_result'
        db.session.commit()
        socketio.emit('phase_update', {'room_id': room_id, 'phase': room.phase}, room=room_id)

    return redirect(url_for('room', room_id=room_id, participant_id=from_id))

@app.route('/start_rebrainstorming/<room_id>', methods=['POST'])
def start_rebrainstorming(room_id):
    room = Room.query.get(room_id)
    if room:
        room.phase = 'rebrainstorming'
        room.round = 2  # ラウンドを2に設定
        participants = Participant.query.filter_by(room_id=room_id).all()

        for idx, p in enumerate(participants):
            p.is_ready = False
            p.has_resubmitted = False

        db.session.commit()
        socketio.emit('phase_update', {'room_id': room_id, 'phase': 'rebrainstorming'}, room=room_id)

    participant_id = request.args.get("participant_id")
    return redirect(url_for('room', room_id=room_id, participant_id=participant_id))

if __name__ == '__main__':
    socketio.run(app, debug=True)
