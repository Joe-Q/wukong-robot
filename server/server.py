import json
from datetime import timedelta
from robot import config, utils
import base64
import tornado.web
import tornado.ioloop
from tornado import gen
import tornado.httpserver
import tornado.options
import hashlib
import threading
import logging
import asyncio
import subprocess
import os
import time
import yaml

from tornado.websocket import WebSocketHandler


logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

conversation, wukong = None, None

class BaseHandler(tornado.web.RequestHandler):
    def isValidated(self):
        return self.get_cookie("validation") == config.get('/server/validate', '')
    def validate(self, validation):
        return validation == config.get('/server/validate', '')


class MainHandler(BaseHandler):

    @tornado.web.asynchronous
    @gen.coroutine
    def get(self):
        global conversation
        if not self.isValidated():
            self.redirect("/login")
            return
        if conversation:
            self.render('index.html', history=conversation.getHistory())
        else:
            self.render('index.html', history=[])

class ChatHandler(BaseHandler):

    @tornado.web.asynchronous
    @gen.coroutine
    def post(self):
        global conversation        
        if self.validate(self.get_argument('validate')):
            if self.get_argument('type') == 'text':
                query = self.get_argument('query')
                uuid = self.get_argument('uuid')
                conversation.doResponse(query, uuid)
                res = {'code': 0}
                self.write(json.dumps(res));
            elif self.get_argument('type') == 'voice':
                voice_data = self.get_argument('voice')
                tmpfile = utils.write_temp_file(base64.b64decode(voice_data), '.wav')
                fname, suffix = os.path.splitext(tmpfile)
                nfile = fname + '-16k' + suffix
                # downsampling
                soxCall = 'sox ' + tmpfile + \
                          ' ' + nfile + ' rate 16k'
                p = subprocess.call([soxCall], shell=True, close_fds=True)
                utils.check_and_delete(tmpfile)
                print(tmpfile)
                conversation.doConverse(nfile)
                res = {'code': 0, 'message': 'ok'};
                self.write(json.dumps(res))
            else:
                res = {'code': 1, 'message': 'illegal type'};
                self.write(json.dumps(res))
        else:
            res = {'code': 1, 'message': 'illegal visit'};
            self.write(json.dumps(res))
        self.finish()
        
        
class GetHistoryHandler(BaseHandler):

    @tornado.web.asynchronous
    @gen.coroutine
    def get(self):
        global conversation
        if not self.validate(self.get_argument('validate')):
            res = {'code': 1, 'message': 'illegal visit'};
            self.write(json.dumps(res))
        else:
            res = {'code': 0, 'message': 'ok', 'history': json.dumps(conversation.getHistory())}
            self.write(json.dumps(res));
        self.finish()


class GetConfigHandler(BaseHandler):

    @tornado.web.asynchronous
    @gen.coroutine
    def get(self):
        if not self.validate(self.get_argument('validate')):
            res = {'code': 1, 'message': 'illegal visit'};
            self.write(json.dumps(res))
        else:
            res = {'code': 0, 'message': 'ok', 'config': config.getText(), 'sensitivity': config.get('sensitivity', 0.5)}
            self.write(json.dumps(res));
        self.finish()


class OperateHandler(BaseHandler):

    def post(self):
        global wukong
        if self.validate(self.get_argument('validate')):
            if self.get_argument('type') == 'restart':
                res = {'code': 0, 'message': 'ok'}
                self.write(json.dumps(res))
                self.finish()
                time.sleep(3)
                wukong.restart()
            else:
                res = {'code': 1, 'message': 'illegal type'}
                self.write(json.dumps(res))
                self.finish()
        else:
            res = {'code': 1, 'message': 'illegal visit'}
            self.write(json.dumps(res))
            self.finish()

class ConfigHandler(BaseHandler):

    @tornado.web.asynchronous
    @gen.coroutine
    def get(self):
        if not self.isValidated():
            self.redirect("/login")
        else:
            self.render('config.html', sensitivity=config.get('sensitivity'))

    def post(self):
        global conversation        
        if self.validate(self.get_argument('validate')):
            configStr = self.get_argument('config')
            try:
                yaml.load(configStr)
                config.dump(configStr)
                res = {'code': 0, 'message': 'ok'};
                self.write(json.dumps(res))
            except:
                res = {'code': 1, 'message': 'YAML解析失败，请检查内容'};
                self.write(json.dumps(res))
        else:
            res = {'code': 1, 'message': 'illegal visit'};
            self.write(json.dumps(res))
        self.finish()
    

        
class LoginHandler(BaseHandler):
    
    @tornado.web.asynchronous
    @gen.coroutine
    def get(self):
        self.render('login.html', error=None)

    @tornado.web.asynchronous
    @gen.coroutine
    def post(self):
        if self.get_argument('username') == config.get('/server/username') and \
           hashlib.md5(self.get_argument('password').encode('utf-8')).hexdigest() \
           == config.get('/server/validate'):
            self.set_cookie("validation", config.get('/server/validate'))
            self.redirect("/")
        else:
            self.render('login.html', error="登录失败")


class LogoutHandler(BaseHandler):
    
    @tornado.web.asynchronous
    @gen.coroutine
    def get(self):
        if self.isValidated():
            self.set_cookie("validation", '')
        self.redirect("/login")


settings = {
    "cookie_secret" : b'*\xc4bZv0\xd7\xf9\xb2\x8e\xff\xbcL\x1c\xfa\xfeh\xe1\xb8\xdb\xd1y_\x1a',
    "template_path": "server/templates",
    "static_path": "server/static",
    "debug": True
}

application = tornado.web.Application([
    (r"/", MainHandler),
    (r"/login", LoginHandler),
    (r"/gethistory", GetHistoryHandler),
    (r"/chat", ChatHandler),
    (r"/config", ConfigHandler),
    (r"/getconfig", GetConfigHandler),
    (r"/operate", OperateHandler),
    (r"/logout", LogoutHandler),
], **settings)


def start_server(con, wk):
    global conversation, wukong
    conversation = con
    wukong = wk
    if config.get('/server/enable', False):
        host = config.get('/server/host', '0.0.0.0')
        port = config.get('/server/port', '5000')
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
            application.listen(int(port))
            tornado.ioloop.IOLoop.instance().start()
        except Exception as e:
            logger.critical('服务器启动失败: {}'.format(e))
        

def run(conversation, wukong):
    t = threading.Thread(target=lambda: start_server(conversation, wukong))
    t.start()
