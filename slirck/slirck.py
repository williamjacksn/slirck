import aiohttp.web
import argparse
import asyncio
import datetime
import json
import pathlib
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


class Config:
    def __contains__(self, item):
        return item in self.data

    def __getitem__(self, item):
        return self.data[item]

    def __init__(self, path):
        self.path = path
        self.data = {}
        if self.path.exists():
            with self.path.open() as f:
                self.data = json.load(f)

    def __setitem__(self, key, value):
        self.data[key] = value
        self._flush()

    def _flush(self):
        with self.path.open('w') as f:
            json.dump(self.data, f, indent=2, sort_keys=True)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def keys(self):
        return self.data.keys()

    def remove(self, key):
        if key in self.data:
            del self.data[key]
            self._flush()

    def set(self, key, value):
        self[key] = value
        self._flush()


class Slack:

    def __init__(self, config):
        self.config = config

    @staticmethod
    def call(method, params=None):
        url = 'https://slack.com/api/' + method
        if params is None:
            params = {}
        data = urllib.parse.urlencode(params).encode()
        try:
            response = urllib.request.urlopen(url, data)
        except urllib.error.HTTPError as e:
            log('** Error talking to Slack: {}'.format(e))
            return None
        return json.loads(response.read().decode())

    def channels_join(self, name):
        method = 'channels.join'
        params = {'token': self.config['slack_token'], 'name': name}
        response = self.call(method, params)
        if not response['ok']:
            log('** Error sending {}: {}'.format(method, params))
            log('** {}'.format(response['error']))
        return response

    def chat_post_message(self, channel, text, username):
        method = 'chat.postMessage'
        params = {'token': self.config['slack_token'], 'channel': channel,
                  'text': text, 'username': username}
        response = self.call(method, params)
        if not response['ok']:
            log('** Error sending {}: {}'.format(method, params))
            log('** {}'.format(response['error']))
            if response['error'] == 'channel_not_found':
                self.channels_join(channel)
        return response


class KernelClient(asyncio.Protocol):

    def __call__(self):
        return self

    def __init__(self, config, verbose=False):
        self._b = b''
        self._t = None
        self.config = config
        self.verbose = verbose
        self.slack = Slack(config)

    def connection_made(self, transport):
        self._t = transport
        if self.verbose:
            log('** Requesting stream from kernel')
        self.send_to_kernel('stream.start')

    def data_received(self, data):
        self._b = self._b + data
        lines = self._b.split(b'\n')
        self._b = lines.pop()
        for line in lines:
            self.process_line(line)

    def handle_irc_message(self, network, message):
        tokens = message.split()
        if len(tokens) > 1 and tokens[1] == 'PRIVMSG':
            sender = tokens[0]
            nick = sender.lstrip(':').split('!')[0]
            target = tokens[2]
            text = message.split(' :', 1)[1]
            if target.startswith('#'):
                slack_channel = '#' + network + '-' + target.lstrip('#')
            else:
                slack_channel = '@' + self.config['slack_username']
            if self.verbose:
                log('** Attempting to send message to Slack')
            self.slack.chat_post_message(slack_channel, text, nick)

    def out(self, message):
        """

        :type message: dict
        """
        line = json.dumps(message)
        data = line.encode() + b'\n'
        if self.verbose:
            log('=> {!r}'.format(data))
        self._t.write(data)

    def process_line(self, line):
        if self.verbose:
            log('<= {!r}'.format(line))
        message = json.loads(line.decode())
        if 'method' in message and message['method'] == 'handler':
            params = message['params']
            self.handle_irc_message(params['network'], params['message'])

    def send_to_kernel(self, method, params=None):
        if params is None:
            params = {}
        params['secret'] = self.config['kernel_secret']
        message = {'jsonrpc': '2.0', 'id': str(uuid.uuid4()), 'method': method,
                   'params': params}
        self.out(message)


def on_action(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    target = tokens[2]
    if bot.is_irc_channel(target):
        source = tokens[0].lstrip(':')
        nick, _, _ = bot.parse_hostmask(source)
        text = ' '.join(tokens[4:])
        slack_channel = bot.c['channel_map'][target]
        Slack.chat_post_message(token, slack_channel, text, nick)


def on_join(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, user, host = bot.parse_hostmask(source)
    irc_channel = tokens[2].lstrip(':')
    slack_channel = bot.c['channel_map'][irc_channel]
    text = '_joined {}_ [{}@{}]'.format(irc_channel, user, host)
    Slack.chat_post_message(token, slack_channel, text, nick)


def on_nick(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    old_nick, _, _ = bot.parse_hostmask(source)
    new_nick = tokens[2].lstrip(':')
    irc_channels = [channel for channel, members in bot.members.items()
                    if new_nick in members]
    text = '_is now known as *{}*_'.format(new_nick)
    for irc_channel in irc_channels:
        slack_channel = bot.c['channel_map'][irc_channel]
        Slack.chat_post_message(token, slack_channel, text, old_nick)


def on_privmsg(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    target = tokens[2]
    source = tokens[0].lstrip(':')
    nick, _, _ = bot.parse_hostmask(source)
    text = message.split(' :', maxsplit=1)[1]
    if bot.is_irc_channel(target):
        slack_channel = bot.c['channel_map'][target]
        Slack.chat_post_message(token, slack_channel, text, nick)


def on_quit(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, _, _ = bot.parse_hostmask(source)
    text = message.split(' :', maxsplit=1)[1]
    text = '_quit_ [{}]'.format(text)
    irc_channels = [channel for channel, members in bot.members.items()
                    if nick in members]
    for irc_channel in irc_channels:
        slack_channel = bot.c['channel_map'][irc_channel]
        Slack.chat_post_message(token, slack_channel, text, nick)


def on_rpl_endofmotd(_, bot):
    if 'irc:nickservpass' in bot.c:
        bot.send_privmsg('nickserv', 'identify ' + bot.c['irc:nickservpass'])
    for channel in bot.c['channel_map']:
        bot.out('JOIN ' + channel)


def generate_config(path: pathlib.Path):
    default_config = {
        'kernel_secret': str(uuid.uuid4()),
        'kernel_host': 'localhost',
        'kernel_port': random.randint(49152, 65535),
        'slack_token': 'PUT SLACK TOKEN HERE',
        'slack_username': 'username',
        'web_host': '0.0.0.0',
        'web_port': random.randint(49152, 65535)
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        json.dump(default_config, f, indent=2, sort_keys=True)


def log(m):
    print('{} {}'.format(datetime.datetime.utcnow(), m))
    sys.stdout.flush()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true')
    return parser.parse_args()


def main():
    log('** Starting up')
    args = parse_args()
    if args.verbose:
        log('** Verbose logging is turned on')

    config_path = pathlib.Path.home() / '.config/slirck/config.json'
    if config_path.exists():
        try:
            c = Config(config_path)
        except json.JSONDecodeError:
            log('** The config file is invalid')
            sys.exit()
    else:
        log('** No config file found')
        generate_config(config_path)
        log('** I generated a new config file at {}'.format(config_path))
        log('** Edit it and try again')
        sys.exit()

    kc = KernelClient(c, args.verbose)

    def receive_from_slack(request):
        rv = aiohttp.web.Response()
        data = yield from request.content.read()
        data = urllib.parse.parse_qs(data.decode())
        user_id = data.get('user_id')
        if user_id is None or user_id[0] == 'USLACKBOT':
            return rv

        if args.verbose:
            log('** Processing message from Slack to IRC')
        text = data['text'][0]
        slack_channel = data['channel_name'][0]
        net = slack_channel.split('-')[0]
        irc_channel = '#' + slack_channel.split('-', 1)[1]

        if irc_channel is not None:
            message = 'PRIVMSG ' + irc_channel + ' :' + text
            kc.send_to_kernel('network.send', {'name': net, 'message': message})
        return rv

    app = aiohttp.web.Application()
    app.router.add_route('POST', '/', receive_from_slack)
    handler = app.make_handler()

    loop = asyncio.get_event_loop()

    kernel_port = c['kernel_port']
    kernel_host = c['kernel_host']
    log('** Connecting to kernel at {}:{}'.format(kernel_host, kernel_port))
    coro = loop.create_connection(kc, kernel_host, kernel_port)
    loop.run_until_complete(coro)

    web_host = c['web_host']
    web_port = c['web_port']
    log('** Listening for Slack messages on {}:{}'.format(web_host, web_port))
    f = loop.create_server(handler, web_host, web_port)
    loop.run_until_complete(f)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()

if __name__ == '__main__':
    main()
