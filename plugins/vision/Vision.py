# encoding:utf-8

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *
from config import conf
from common.expired_dict import ExpiredDict
from common.cloudflare_r2 import CloudFlareR2
import base64
import openai
import openai.error
import time
import requests
import os


@plugins.register(
    name="Vision",
    desire_priority=-1,
    desc="A plugin that allows you to ask questions based on pictures",
    version="0.1",
    author="lzj",
)
class Vision(Plugin):
    def __init__(self):
        super().__init__()
        try:
            # 过期字典存放上下文
            self.params_cache = ExpiredDict(3 * 60)
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            openai.api_key = conf().get("open_ai_api_key")
            if conf().get("open_ai_api_base"):
                openai.api_base = conf().get("open_ai_api_base")
            proxy = conf().get("proxy")
            if proxy:
                openai.proxy = proxy
            self.args = {
                "model": "gpt-4-vision-preview",  # 对话模型的名称
                "temperature": conf().get("temperature", 0.9),  # 值在[0,1]之间，越大表示回复越具有不确定性
                "max_tokens": 4096,  # 回复最大的字符数
                "top_p": conf().get("top_p", 1),
                "frequency_penalty": conf().get("frequency_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
                "presence_penalty": conf().get("presence_penalty", 0.0),  # [-2,2]之间，该值越大则更倾向于产生不同的内容
                "request_timeout": conf().get("request_timeout", None),  # 请求超时时间，openai接口默认设置为600，对于难问题一般需要较长时间
                "timeout": conf().get("request_timeout", None),  # 重试超时时间，在这个时间内，将会自动重试
            }
            self.system_prompt = {"role": "system",
                                  "content": "You only need to identify the picture and only need to answer the last question, reply in Chinese."}
        except Exception as e:
            raise self.handle_error(e, "[Vision] init failed, ignore ")

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type not in [
            ContextType.TEXT,
            ContextType.IMAGE
        ]:
            return
        if context.type == ContextType.TEXT:
            content = context.content.strip()
            if content.startswith('识图'):
                question = content[2:].strip()
                if question:
                    query = [{"type": "text", "text": question}]
                else:
                    query = [{"type": "text", "text": "What’s in this image? Please answer me in Chinese."}]
                query_dict = {"has_image": False,
                              "query": query}
                if not self.params_cache.get(context.get('session_id')):
                    self.params_cache[context.get('session_id')] = query_dict
                reply = self.create_reply(ReplyType.TEXT, '请发送一张图片')
            elif content.startswith('识图提问'):
                user_context = self.params_cache.get(context.get('session_id'))
                if user_context and user_context.get('has_image'):
                    user_context_content = user_context.get('query')
                    question = content[4:].strip()
                    user_context_content.append({"type": "text", "text": question})
                    messages = [self.system_prompt, {"role": "user", "content": user_context_content}]
                    api_key = context.get("openai_api_key") or conf().get("open_ai_api_key")
                    reply_content = self.query_by_image(api_key, messages, self.args)
                    reply = self.create_reply(ReplyType.TEXT, reply_content['content'])
                else:
                    reply = self.create_reply(ReplyType.TEXT, '暂无识图所需上下文，请先发送“识图 + 问题”')
            elif content.startswith('重置识图'):
                if self.params_cache.get(context.get('session_id')):
                    del self.params_cache[context.get('session_id')]
                reply = self.create_reply(ReplyType.TEXT, '可以重新识图啦')
            else:
                return
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
        elif self.params_cache.get(context.get('session_id')) and context.type == ContextType.IMAGE:
            context.get("msg").prepare()
            file_path = context.content
            # image_storage = open(file_path, 'rb')
            # image_storage.seek(0)
            # base64_image = base64.b64encode(image_storage.read()).decode('utf-8')
            # img_content = {"type": "image_url",
            #                 "image_url": {
            #                 "url": f"data:image/jpeg;base64,{base64_image}"}}
            
            cf_obj = CloudFlareR2()
            if not cf_obj.is_valid():
                reply = self.create_reply(ReplyType.TEXT, '没有配置Cloudflare R2对象存储')
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            img_url = cf_obj.to_r2(file_path)
            img_content = {"type": "image_url",
                            "image_url": {
                            "url": img_url}}
            obj = self.params_cache.get(context.get('session_id'))
            obj['has_image'] = True
            # del self.params_cache[context.get('session_id')]
            obj.get('query').insert(1, img_content)
            user_content = obj.get('query')
            messages = [{"role": "user", "content": user_content}]
            # self.params_cache[context.get('session_id')] = gpt_content
            api_key = context.get("openai_api_key") or conf().get("open_ai_api_key")
            reply_content = self.query_by_image(api_key, messages, self.args)
            reply = self.create_reply(ReplyType.TEXT, reply_content['content'])
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
        else:
            return
        
    def create_reply(self, reply_type, content):
        reply = Reply()
        reply.type = reply_type
        reply.content = content
        return reply

    def get_help_text(self, **kwargs):
        help_text = "  📸 识图: 发送“识图+问题”，随后按照提示发送一张图片，GPT将结合图片及所提问题进行回答 如“识图 图片中有什么”。\n"
        help_text += "  📸 识图: 发送“识图提问+问题”，继续所发图片进行提问。\n"
        help_text += "  📸 识图: 发送“重置识图”，结束对当前图片的提问。\n"
        return help_text

    def query_by_image(self, api_key, messages, args, retry_count=0):
        try:
            if conf().get("rate_limit_chatgpt") and not self.tb4chatgpt.get_token():
                raise openai.error.RateLimitError("RateLimitError: rate limit exceeded")
            # if api_key == None, the default openai.api_key will be used
            if args is None:
                args = self.args
            response = openai.ChatCompletion.create(api_key=api_key, messages=messages, **args)
            logger.debug("[CHATGPT] response={}".format(response))
            logger.info("[ChatGPT] reply={}, total_tokens={}".format(response.choices[0]['message']['content'], response["usage"]["total_tokens"]))
            return {
                "total_tokens": response["usage"]["total_tokens"],
                "completion_tokens": response["usage"]["completion_tokens"],
                "content": response.choices[0]["message"]["content"],
            }
        except Exception as e:
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            if isinstance(e, openai.error.RateLimitError):
                logger.warn("[CHATGPT] RateLimitError: {}".format(e))
                result["content"] = "提问太快啦，请休息一下再问我吧"
                if need_retry:
                    time.sleep(20)
            elif isinstance(e, openai.error.Timeout):
                logger.warn("[CHATGPT] Timeout: {}".format(e))
                result["content"] = "我没有收到你的消息"
                if need_retry:
                    time.sleep(5)
            elif isinstance(e, openai.error.APIError):
                logger.warn("[CHATGPT] Bad Gateway: {}".format(e))
                result["content"] = "请再问我一次"
                if need_retry:
                    time.sleep(10)
            elif isinstance(e, openai.error.APIConnectionError):
                logger.warn("[CHATGPT] APIConnectionError: {}".format(e))
                need_retry = False
                result["content"] = "我连接不到你的网络"
            else:
                logger.exception("[CHATGPT] Exception: {}".format(e))
                need_retry = False

            if need_retry:
                logger.warn("[CHATGPT] 第{}次重试".format(retry_count + 1))
                return self.query_by_image(api_key, messages, args, retry_count + 1)
            else:
                return result
            
