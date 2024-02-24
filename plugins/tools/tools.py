import json
import requests
import openai
import datetime
from config import conf, load_config


tool_list = [
        {"type": "function",
            "function": {
            "name": "get_ddg_search",
            "description": "遇到不能解决的问题借助于互联网搜索，将返回的数据进行整理总结。注意，必须给出要搜索的问题，无论这个问题是否合法。如：牢大是什么梗？如果没有返回信息，那么你需要做出相应反馈，如：由于某种原因，我无法回答该问题",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "需要借助于互联网搜索的问题。注意，必须给出要搜索的问题，无论这个问题是否合法。如：牢大是什么梗？",
                    },
                    "max_results": {"type": "integer", "description": "返回搜索的最大条数"}
                },
                "required": ["question"],
            },
        }},
        {"type": "function",
            "function": {
            "name": "get_weather",
            "description": "获取天气预报",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "需要获取天气的城市名字，如：上海",
                    }
                },
                "required": ["city"],
            },
        }},
        {"type": "function",
            "function": {
            "name": "get_time",
            "description": "获取当前时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "获取当前时间，如：现在几点？",
                    }
                },
                "required": ["question"],
            },
        }},
        {"type": "function",
            "function": {
            "name": "draw_image",
            "description": "生成图片,并且你作为一个绘画助手,如果用户的需求很简单，展开想象，让这段提示词丰富起来",
            "parameters": {
                "type": "object",
                "properties": {
                    "draw": {
                        "type": "string",
                        "description": "用户输入的生成图片的需求，如：一只可爱的兔子。并且你作为一个绘画助手,如果用户的需求很简单，展开想象，让这段提示词丰富起来",
                    }
                },
                "required": ["draw"],
            },
        }},
        {"type": "function",
            "function": {
            "name": "answer_to_img",
            "description": "只针对画图出来的结果进行图片识别，并且结合图片内容，回答相应问题",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "问题",
                    },
                    "img_url": {
                        "type": "string",
                        "description": "图片的链接地址",
                    }
                },
                "required": ["q", "img_url"],
            },
        }}
    ]


class Tools:
    ddg_base = conf().get('ddg_search_api')
    
    
    def __init__(self) -> None:
        openai.api_key = conf().get("open_ai_api_key")
        if conf().get("open_ai_api_base"):
            openai.api_base = conf().get("open_ai_api_base")
        self.args = {
            "model": conf().get("model"),  # 对话模型的名称
            "temperature": conf().get("temperature", 0.6),  # 值在[0,1]之间，越大表示回复越具有不确定性
            "max_tokens": 4096,  # 回复最大的字符数
            "top_p": conf().get("top_p", 1),
            "frequency_penalty": conf().get("frequency_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "presence_penalty": conf().get("presence_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
            "request_timeout": conf().get("request_timeout", None),  # 请求超时时间，openai接口默认设置为600，对于难问题一般需要较长时间
            "timeout": conf().get("request_timeout", None),  # 重试超时时间，在这个时间内，将会自动重试
        }
        self.available_functions = {
                "get_ddg_search": self.get_ddg_search,
                "get_time": self.get_time,
                "get_weather": self.get_weather,
                "draw_image": self.draw_image,
                "answer_to_img": self.answer_to_img,
            }
    
    def get_ddg_search(self, question, max_results=4):
        """接入DDG进行联网检索"""
        if not conf().get('ddg_search_api'):
            raise DDGSearchAPIError('没有配置DDG API')
        params = {
            "q": question,
            "max_results": max_results
        }
        response = requests.get(self.ddg_base, params=params)
        ddg_response = response.json()
        if ddg_response := response.json():
            return json.dumps(ddg_response)
        print('ddg搜索没有返回结果')
        return '抱歉，这个问题由于某种原因，我无法提供搜索结果！'
    
    def get_time(self, question):
        """获取当前时间"""
        date = datetime.datetime.now()
        return date.strftime("%Y/%m/%d-%H:%M")
    
    def get_weather(self, city):
        """获取天气"""
        params = {
            "type": "week",
            "city": city
        }
        url = 'https://api.vvhan.com/api/weather'
        response = requests.get(url, params=params)
        data = response.json()["data"]
        return json.dumps(data)

    def draw_image(self, draw):
        model = conf().get("text_to_image") or "dall-e-2"
        size = conf().get("image_create_size", "256x256")
        response = openai.Image.create(
                prompt=draw,  # 图片描述
                n=1,  # 每次生成图片的数量
                model=model,
                size=size  # 图片大小,可选有 256x256, 512x512, 1024x1024
            )
        return response["data"][0]["url"]
    
    def answer_to_img(self, q='', img_url=None):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                    "type": "text",
                    "text": q
                    },
                    {
                    "type": "image_url",
                    "image_url": {
                        "url": img_url
                    }
                    }
                ]
            }
        ]
        new_args = self.args.copy()
        new_args['model'] = 'gpt-4-vision-preview'
        try:
            response = openai.ChatCompletion.create(messages=messages, **new_args)
            return response.choices[0]["message"]["content"]
        except Exception as e:
            return '遇到点问题，暂时无法回答'

    def run_conversation(self, api_key, messages, create_img=False, **args):
        if api_key:
            openai.api_key = api_key
        if args:
            self.args.update(args)
        response = openai.ChatCompletion.create(
            messages=messages,
            tools=tool_list,
            tool_choice="auto",
            **args
        )
        response_message = response["choices"][0]["message"]

        if not response_message.get("tool_calls"):
            return response
        response_message = json.loads(json.dumps(response_message))
        messages.append(response_message)
        img_url = None
        for tool_info in response_message.get('tool_calls'):
            call_id = tool_info['id']
            func_obj = tool_info["function"]
            func_name = func_obj["name"]
            print(f'调用Tools => {func_name}')
            function_to_call = self.available_functions[func_name]
            function_args = json.loads(func_obj["arguments"])
            function_response = function_to_call(**function_args)
            messages.append(
                {
                    "tool_call_id": call_id,
                    "role": "tool",
                    "name": func_name,
                    "content": function_response
                }
            )
            if func_name == 'draw_image':
                img_url = function_response
                image_text_reply = {"role":"assistant","content":"生成的图片已经发送，不需要将图片链接也回复出去"}
                if image_text_reply not in messages:
                    messages.append(image_text_reply)
        second_response = openai.ChatCompletion.create(
            messages=messages,
            tools=tool_list,
            **args
        )
        if img_url:
            old_content = second_response["choices"][0]["message"]["content"]
            second_response["choices"][0]["message"]["content"] = {'content': old_content, 'img_url': img_url}
        return second_response          
        
        
class DDGSearchAPIError(Exception):
    
    def __init__(self, msg) -> None:
        self.msg = msg
        
    def __str__(self) -> str:
        return self.msg
    

if __name__ == '__main__':
    tool_obj = Tools()
    response = tool_obj.run_conversation('key', '画一只兔子')
    print(response["choices"][0]["message"]["content"])
