from typing import Any, Dict
import openai
import json

class Gpt_api:
    def __init__(self):
        pass
    
    def get_chat_completion(self,messages, format):
        # OpenAIインスタンス生成　#APIキー
        # API呼び出し
        chat_completion = openai.ChatCompletion.create(
            messages=messages,  # 要求する内容を入力
            response_format=format,  # フォーマットの設定
            model="gpt-4o-2024-08-06",
        )
        # データ取得
        return chat_completion.choices[0].message.content
    def generate_research_themes(self,evaluation_point) -> Dict[str, Any]:
        response_format = {
            "type": "json_schema",  # json_schemaを設定
            "json_schema": {
                "name": "evaluation_response",
                "strict": True,
                "schema": {  # schmaにてデータ型を設定
                    "type": "object",  # データ型を指定。今回はオブジェクト型(辞書)
                    "properties": {
                        "要約": {
                            "type": "string"
                        },  # keyを"common_content",valueを文字列
                        "アドバイス": {
                            "type": "string"
                        }, 
                        "評価": {  # keyを"themes", valueを配列
                            "type": "array",  # 配列の中身の設定
                            "items": {  # 配列のときはitemsとして要素の構造を設定
                                "type": "object",  # 配列の要素はオブジェクト型(辞書)
                                "properties": {
                                },
                                "required": [
                                    
                                ],  # requiredで必須項目を指定
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["要約", "評価","アドバイス"],  # requiredで必須項目を指定
                    "additionalProperties": False,
                },
            },
        }

        for eva in evaluation_point:
            response_format["json_schema"]["schema"]["properties"]["評価"]["items"]["properties"][eva] = {"type": "number"}
        response_format["json_schema"]["schema"]["properties"]["評価"]["items"]["required"] = evaluation_point

        return response_format
    
    def summerize(self,idea, feedbacks, criteria_list):
        feedbacks = ",".join(feedbacks)
        format = self.generate_research_themes(criteria_list)
        evaluation_point_str = ",".join(criteria_list)
        prompt = f"アイデアは{idea} アイデアに対する意見は{feedbacks} アイデアに対する意見に基づいて{evaluation_point_str}の各評価軸に沿って5段階評価をしてください. アイデアに対する意見を要約してください.要約の際に公序良俗に反する発言は省いてください．また，意見に評価軸に基づく評価が含まれていない場合にはあなたの主観に基づいて5段階評価を行ってください．アドバイスについては，寄せられた意見に基づいてアイデアをよりブラッシュアップするためにアドバイスをしてあげてください．また，意見の中にはなかった視点に基づいてアドバイスしてもいいです．意味不明なアイデアに対しては5段階中最低評価でお願いします．"

        messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]

        # OPENAIのAPI呼び出し
        response = self.get_chat_completion(messages, format)
        data = json.loads(response)
        return data
    
"""api = Gpt_api()
criteria_list = ["実現可能性", "奇抜さ", "新規性"]
idea = "「AIが挑発する『話しかけたら負けゲーム』で性格診断！」AIが挑発し続け、どのタイミングで話しかけるかを分析して性格を診断。忍耐力や衝動性を測定し、ゲーミフィケーション化！"
feedbacks = ["実現はできそうだが，すごく平凡でつまらない．新規性はあるかもしれない",
             "APIを使えば簡単にできそう．どんな挑発をしてくるのかわからないので，奇抜さについては判断しにくい"]
print(api.summerize(idea, feedbacks, criteria_list))"""