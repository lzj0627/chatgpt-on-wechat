"""
钉钉通道接入

@author huiwen
@Date 2023/11/28
"""
import copy
import json
# -*- coding=utf-8 -*-
import logging
import time

import dingtalk_stream
from dingtalk_stream import AckMessage
from dingtalk_stream.card_replier import AICardReplier
from dingtalk_stream.card_replier import AICardStatus
from dingtalk_stream.card_replier import CardReplier

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.dingtalk.dingtalk_message import DingTalkMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.time_check import time_checker
from config import conf
import cv2
import os
import datetime
from common.tmp_dir import TmpDir
from common.cloudflare_r2 import CloudFlareR2


class CustomAICardReplier(CardReplier):
    def __init__(self, dingtalk_client, incoming_message):
        super(AICardReplier, self).__init__(dingtalk_client, incoming_message)

    def start(
            self,
            card_template_id: str,
            card_data: dict,
            recipients: list = None,
            support_forward: bool = True,
    ) -> str:
        """
        AI卡片的创建接口
        :param support_forward:
        :param recipients:
        :param card_template_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.PROCESSING
        return self.create_and_send_card(
            card_template_id,
            card_data_with_status,
            at_sender=True,
            at_all=False,
            recipients=recipients,
            support_forward=support_forward,
        )


# 对 AICardReplier 进行猴子补丁
AICardReplier.start = CustomAICardReplier.start


def _check(func):
    def wrapper(self, cmsg: DingTalkMessage):
        msgId = cmsg.msg_id
        if msgId in self.receivedMsgs:
            logger.info("DingTalk message {} already received, ignore".format(msgId))
            return
        self.receivedMsgs[msgId] = True
        create_time = cmsg.create_time  # 消息时间戳
        if conf().get("hot_reload") == True and int(create_time) < int(time.time()) - 60:  # 跳过1分钟前的历史消息
            logger.debug("[DingTalk] History message {} skipped".format(msgId))
            return
        if cmsg.my_msg and not cmsg.is_group:
            logger.debug("[DingTalk] My message {} skipped".format(msgId))
            return
        return func(self, cmsg)

    return wrapper


@singleton
class DingTalkChanel(ChatChannel, dingtalk_stream.ChatbotHandler):
    dingtalk_client_id = conf().get('dingtalk_client_id')
    dingtalk_client_secret = conf().get('dingtalk_client_secret')
    dingtalk_message_card_template_id = conf().get('dingtalk_card_template_id')
    dingtalk_video_card_template_id = conf().get('dingtalk_video_card_template_id')

    def setup_logger(self):
        logger = logging.getLogger()
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('%(asctime)s %(name)-8s %(levelname)-8s %(message)s [%(filename)s:%(lineno)d]'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger

    def __init__(self):
        super().__init__()
        super(dingtalk_stream.ChatbotHandler, self).__init__()
        self.logger = self.setup_logger()
        # 历史消息id暂存，用于幂等控制
        self.receivedMsgs = ExpiredDict(conf().get("expires_in_seconds"))
        logger.info("[DingTalk] client_id={}, client_secret={} ".format(
            self.dingtalk_client_id, self.dingtalk_client_secret))
        # 无需群校验和前缀
        conf()["group_name_white_list"] = ["ALL_GROUP"]
        # 单聊无需前缀
        conf()["single_chat_prefix"] = [""]
        self.r2 = CloudFlareR2()

    def startup(self):
        credential = dingtalk_stream.Credential(self.dingtalk_client_id, self.dingtalk_client_secret)
        client = dingtalk_stream.DingTalkStreamClient(credential)
        client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, self)
        client.start_forever()

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        try:
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            image_download_handler = self  # 传入方法所在的类实例
            dingtalk_msg = DingTalkMessage(incoming_message, image_download_handler)

            if dingtalk_msg.is_group:
                self.handle_group(dingtalk_msg)
            else:
                self.handle_single(dingtalk_msg)
            return AckMessage.STATUS_OK, 'OK'
        except Exception as e:
            logger.error(f"dingtalk process error={e}")
            return AckMessage.STATUS_SYSTEM_EXCEPTION, 'ERROR'

    @time_checker
    @_check
    def handle_single(self, cmsg: DingTalkMessage):
        # 处理单聊消息
        if cmsg.ctype == ContextType.VOICE:
            logger.debug("[DingTalk]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[DingTalk]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE_CREATE:
            logger.debug("[DingTalk]receive image create msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[DingTalk]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[DingTalk]receive text msg: {}".format(cmsg.content))
        else:
            logger.debug("[DingTalk]receive other msg: {}".format(cmsg.content))
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=False, msg=cmsg)
        if context:
            self.produce(context)


    @time_checker
    @_check
    def handle_group(self, cmsg: DingTalkMessage):
        # 处理群聊消息
        if cmsg.ctype == ContextType.VOICE:
            logger.debug("[DingTalk]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[DingTalk]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE_CREATE:
            logger.debug("[DingTalk]receive image create msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[DingTalk]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[DingTalk]receive patpat msg: {}".format(cmsg.content))
        else:
            logger.debug("[DingTalk]receive other msg: {}".format(cmsg.content))
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg)
        context['no_need_at'] = True
        if context:
            self.produce(context)


    def send(self, reply: Reply, context: Context):
        receiver = context["receiver"]
        isgroup = context.kwargs['msg'].is_group
        incoming_message = context.kwargs['msg'].incoming_message

        if conf().get("dingtalk_card_enabled"):
            logger.info("[Dingtalk] sendMsg={}, receiver={}".format(reply, receiver))
            def reply_with_text():
                self.reply_text(reply.content, incoming_message)
            def reply_with_ai_card():
                self.generate_ai_card(reply, incoming_message)
            def reply_with_video_card():
                self.generate_video_card(reply, incoming_message)
            def reply_with_at_text():
                self.reply_text("📢 您有一条新的消息，请查看。", incoming_message)
            def reply_with_ai_markdown():
                button_list, markdown_content = self.generate_button_markdown_content(context, reply)
                self.reply_ai_markdown_button(incoming_message, markdown_content, button_list, "", "📌 内容由AI生成", "",[incoming_message.sender_staff_id])

            if reply.type == ReplyType.TEXT:
                if isgroup:
                    reply_with_ai_card()
                    reply_with_at_text()
                else:
                    reply_with_ai_card()
            elif reply.type == ReplyType.VIDEO_URL:
                if isgroup:
                    reply_with_video_card()
                    reply_with_at_text()
                else:
                    reply_with_video_card()
            elif reply.type in [ReplyType.IMAGE_URL, ReplyType.IMAGE]:
                if isgroup:
                    reply_with_ai_markdown()
                    reply_with_at_text()
                else:
                    reply_with_ai_markdown()
            elif reply.type == ReplyType.IMAGE_AND_TEXT:
                content = reply.content.get('content')
                context.__setitem__('image_url', reply.content.get('img_url'))
                context.__setitem__('promptEn', content)
                reply.content = content
                if isgroup:
                    reply_with_ai_markdown()
                    reply_with_at_text()
                else:
                    reply_with_ai_markdown()
            else:
                # 暂不支持其它类型消息回复
                reply_with_text()
        else:
            self.reply_text(reply.content, incoming_message)


    def generate_button_markdown_content(self, context, reply):
        image_url = context.kwargs.get("image_url")
        promptEn = context.kwargs.get("promptEn")
        reply_text = reply.content
        button_list = []
        markdown_content = reply_text
        if image_url is not None and promptEn is not None:
            button_list = [
                {"text": "查看原图", "url": image_url, "iosUrl": image_url, "color": "blue"}
            ]
            markdown_content = f'{reply_text or promptEn}\n\n!["图片"]({image_url}) '
        logger.debug(f"[Dingtalk] generate_button_markdown_content, button_list={button_list} , markdown_content={markdown_content}")

        return button_list, markdown_content
    
    def generate_ai_card(self, reply, incoming_message):
        """
        钉钉开发者后台创建AI卡片模板
        https://open-dev.dingtalk.com/?spm=ding_open_doc.document.0.0.33a34fc0InhPt7#/
        """
        content_key = "content"
        card_data = {content_key: ""}
        card_instance = dingtalk_stream.AICardReplier(
            self.dingtalk_client, incoming_message
        )
        
        card_instance_id = card_instance.create_and_send_card(
            self.dingtalk_message_card_template_id, card_data, callback_type="STREAM"
        )
        card_instance.streaming(
                card_instance_id,
                content_key=content_key,
                content_value=reply.content,
                append=False,
                finished=True,
                failed=False,
            )
        
    def generate_video_card(self, reply, incoming_message):
        cover = os.path.join(TmpDir().path(), f"{datetime.datetime.now().strftime('%Y%m%d_%H%M_%f')}.png")
        card_data = {'video': reply.content, 'content': '', 'video_cover': ''}
        if getVideoPng(reply.content, cover) and self.r2.is_valid:
            video_cover = self.r2.to_r2(cover)
            card_data['video_cover'] = video_cover
        card_instance = dingtalk_stream.AICardReplier(
            self.dingtalk_client, incoming_message
        )
        
        card_instance_id = card_instance.create_and_send_card(
            self.dingtalk_video_card_template_id, card_data, callback_type="STREAM"
        )
        card_instance.streaming(
                card_instance_id,
                content_key='content',
                content_value=incoming_message.text.content,
                append=True,
                finished=True,
                failed=False,
            )

def getVideoPng(_videoPath, _pngPath):
    vidcap = cv2.VideoCapture(_videoPath)
    for _ in range(1, 30):
         _, image = vidcap.read()
    return cv2.imwrite(_pngPath, image)