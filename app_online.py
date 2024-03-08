# encoding:utf-8

import os
import signal
import sys
import time

from channel import channel_factory
from common import const
from config import load_config, conf
from plugins import *
import threading
from flask import Flask, render_template_string, render_template, jsonify
from lib import itchat


def sigterm_handler_wrap(_signo):
    old_handler = signal.getsignal(_signo)

    def func(_signo, _stack_frame):
        logger.info("signal {} received, exiting...".format(_signo))
        conf().save_user_datas()
        if callable(old_handler):  #  check old_handler
            return old_handler(_signo, _stack_frame)
        sys.exit(0)

    signal.signal(_signo, func)


def start_channel(channel_name: str):
    channel = channel_factory.create_channel(channel_name)
    if channel_name in ["wx", "wxy", "terminal", "wechatmp", "wechatmp_service", "wechatcom_app", "wework",
                        const.FEISHU, const.DINGTALK]:
        PluginManager().load_plugins()

    if conf().get("use_linkai"):
        try:
            from common import linkai_client
            threading.Thread(target=linkai_client.start, args=(channel,)).start()
        except Exception as e:
            pass
    channel.startup()
    while True:
        time.sleep(1)


def run():
    try:
        # load config
        load_config()
        # ctrl + c
        sigterm_handler_wrap(signal.SIGINT)
        # kill signal
        sigterm_handler_wrap(signal.SIGTERM)

        # create channel
        channel_name = conf().get("channel_type", "wx")

        if "--cmd" in sys.argv:
            channel_name = "terminal"

        if channel_name == "wxy":
            os.environ["WECHATY_LOG"] = "warn"

        start_channel(channel_name)

        while True:
            time.sleep(1)
    except Exception as e:
        logger.error("App startup failed!")
        logger.exception(e)


app = Flask(__name__)

SUCCESS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport"
        content="width=device-width, user-scalable=no, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="ie=edge">
  <title>微信机器人在线状态</title>
</head>
<body>
  <h1 style="text-align: center">当前机器人在线，无需登录</h1>
</body>
</html>
"""

@app.route('/online')
def online():
    alive, is_logging = itchat.instance.alive, itchat.instance.isLogging
    if not alive:
        # load config
        load_config()
        threading.Thread(target=start_channel, args=('wx',)).start()
        time.sleep(1)
        # 已登录状态 项目手动重启 热重载有一点延迟 再判断一次是否登录
        if alive:
            return render_template_string(SUCCESS_TEMPLATE)
        backend = conf().get('backend')
        url = f"https://login.weixin.qq.com/l/{itchat.instance.uuid}"
        img_url = "https://my.tv.sohu.com/user/a/wvideo/getQRCode.do?text={}".format(url)
        return render_template('online.html', img_url=img_url, backend=backend)
    return render_template_string(SUCCESS_TEMPLATE)

@app.route('/status')
def status():
    alive= itchat.instance.alive
    data = {'alive': alive}
    return jsonify(data)


if __name__ == "__main__":
    app.run('0.0.0.0', 10000)
    
