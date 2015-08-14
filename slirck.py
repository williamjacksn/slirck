import aiohttp.web
import asyncio
import humphrey
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request


class Slack:

    @staticmethod
    def call(method, params=None):
        url = 'https://slack.com/api/' + method
        if params is None:
            params = {}
        data = urllib.parse.urlencode(params).encode()
        response = urllib.request.urlopen(url, data)
        return json.loads(response.read().decode())

    @staticmethod
    def post_message(token, channel, text, username, icon_url=None):
        method = 'chat.postMessage'
        params = {'token': token, 'channel': channel, 'text': text,
                  'username': username}
        if icon_url is not None:
            params['icon_url'] = icon_url
        return Slack.call(method, params)

    @staticmethod
    def set_topic(token, channel, topic):
        method = 'channels.setTopic'
        params = {'token': token, 'channel': channel, 'topic': topic}
        return Slack.call(method, params)


def rw_api_call(path, params=None):
    url = 'http://rainwave.cc/api4/' + path
    if params is None:
        params = {}
    data = urllib.parse.urlencode(params).encode()
    try:
        response = urllib.request.urlopen(url, data=data)
    except urllib.error.HTTPError:
        return None
    if response.status == 200:
        return json.loads(response.read().decode())
    return None


def get_rw_avatar_url(nick, bot):
    nick = nick.lower()
    avatar_cache = bot.c['avatar_cache']
    if nick in avatar_cache:
        return avatar_cache[nick]

    response = rw_api_call('user_search', {'username': nick})
    if response is None:
        return

    user_id = response['user']['user_id']
    params = {'id': user_id, 'user_id': bot.c['rw:user_id'],
              'key': bot.c['rw:key']}
    response = rw_api_call('listener', params)
    if response is None:
        return

    avatar = 'http://rainwave.cc' + response['listener']['avatar']
    avatar_cache[nick] = avatar
    bot.c['avatar_cache'] = avatar_cache
    return avatar


def on_action(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    target = tokens[2]
    if bot.is_irc_channel(target):
        source = tokens[0].lstrip(':')
        nick, _, _ = bot.parse_hostmask(source)
        icon_url = get_rw_avatar_url(nick, bot)
        text = ' '.join(tokens[4:])
        Slack.post_message(token, target, text, nick, icon_url)


def on_join(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, user, host = bot.parse_hostmask(source)
    irc_channel = tokens[2].lstrip(':')
    slack_channel = bot.c['channel_map'][irc_channel]
    text = '_joined {}_ [{}@{}]'.format(irc_channel, user, host)
    icon_url = get_rw_avatar_url(nick, bot)
    Slack.post_message(token, slack_channel, text, nick, icon_url)


def on_nick(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    old_nick, _, _ = bot.parse_hostmask(source)
    icon_url = get_rw_avatar_url(old_nick, bot)
    new_nick = tokens[2].lstrip(':')
    if icon_url is None:
        icon_url = get_rw_avatar_url(new_nick, bot)
    irc_channels = [channel for channel, members in bot.members.items()
                    if new_nick in members]
    text = '_is now known as *{}*_'.format(new_nick)
    for irc_channel in irc_channels:
        Slack.post_message(token, irc_channel, text, old_nick, icon_url)


def on_notice(message, bot):
    token = bot.c['slack:token']
    tokens = message.split(maxsplit=3)
    source = tokens[0].lstrip(':')
    nick, _, _ = bot.parse_hostmask(source)
    icon_url = get_rw_avatar_url(nick, bot)
    text = tokens[3].lstrip(':')
    target = '@' + bot.c['slack:username']
    Slack.post_message(token, target, text, nick, icon_url)


def on_privmsg(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    target = tokens[2]
    source = tokens[0].lstrip(':')
    nick, _, _ = bot.parse_hostmask(source)
    icon_url = get_rw_avatar_url(nick, bot)
    text = message.split(' :', maxsplit=1)[1]
    if bot.is_irc_channel(target):
        slack_channel = bot.c['channel_map'][target]
        Slack.post_message(token, slack_channel, text, nick, icon_url)
    else:
        username = '@' + bot.c['slack:username']
        Slack.post_message(token, username, text, nick, icon_url)


def on_quit(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, _, _ = bot.parse_hostmask(source)
    icon_url = get_rw_avatar_url(nick, bot)
    text = message.split(' :', maxsplit=1)[1]
    m = '_quit_ [{}]'.format(text)
    Slack.post_message(token, bot.c['irc:channel'], m, nick, icon_url)


def on_rpl_endofmotd(_, bot):
    if 'irc:nickservpass' in bot.c:
        bot.send_privmsg('nickserv', 'identify ' + bot.c['irc:nickservpass'])
    for channel, _ in bot.c['channel_map'].items():
        bot.out('JOIN ' + channel)


def on_rpl_topic(message, bot):
    token = bot.c['slack:token']
    tokens = message.split(maxsplit=4)
    irc_channel = tokens[3]
    topic = tokens[4].lstrip(':')
    slack_channel = bot.c['channel_map'][irc_channel]
    Slack.set_topic(token, slack_channel, topic)


def on_topic(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, _, _ = bot.parse_hostmask(source)
    icon_url = get_rw_avatar_url(nick, bot)
    target = tokens[2]
    slack_channel = bot.c['channel_map'][target]
    topic = message.split(' :', maxsplit=1)[1]
    text = '*{}* changed the topic:\n{}'.format(nick, topic)
    Slack.post_message(token, slack_channel, text, nick, icon_url)
    Slack.set_topic(token, slack_channel, topic)


def main():
    config_file = pathlib.Path(__file__).resolve().with_name('_config.json')
    irc = humphrey.IRCClient(config_file)
    irc.c.pretty = True
    irc.debug = True

    irc.ee.on('332', func=on_rpl_topic)
    irc.ee.on('376', func=on_rpl_endofmotd)
    irc.ee.on('ACTION', func=on_action)
    irc.ee.on('JOIN', func=on_join)
    irc.ee.on('NICK', func=on_nick)
    irc.ee.on('NOTICE', func=on_notice)
    irc.ee.on('PRIVMSG', func=on_privmsg)
    irc.ee.on('QUIT', func=on_quit)
    irc.ee.on('TOPIC', func=on_topic)

    def receive_from_slack(request):
        rv = aiohttp.web.Response()
        data = yield from request.content.read()
        data = urllib.parse.parse_qs(data.decode())
        if 'USLACKBOT' in data['user_id']:
            return rv

        if 'command' in data:
            if '/pm' in data['command']:
                irc.log('** Processing /pm from Slack to IRC')
                target, message = data['text'][0].split(maxsplit=1)
                irc.send_privmsg(target.lstrip('@'), message)
                return rv
            elif '/raw' in data['command']:
                irc.log('** Processing /raw from Slack to IRC')
                text = data['text'][0]
                irc.out(text)
                return rv

        irc.log('** Processing message from Slack to IRC')
        speaker = data['user_name'][0]
        text = data['text'][0]
        if 'slack:username' in irc.c:
            if irc.c['slack:username'] == speaker:
                irc.send_privmsg(irc.c['irc:channel'], text)
            else:
                irc.log('## Message username did not match config')
            return rv

        irc.send_privmsg(irc.c['irc:channel'], '<{}> {}'.format(speaker, text))
        return rv

    app = aiohttp.web.Application()
    app.router.add_route('POST', '/', receive_from_slack)
    handler = app.make_handler()

    loop = asyncio.get_event_loop()
    host = irc.c.get('irc:host')
    port = irc.c.get('irc:port')
    coro = loop.create_connection(irc, host, port)
    loop.run_until_complete(coro)

    f = loop.create_server(handler, '0.0.0.0', irc.c['web:port'])
    loop.run_until_complete(f)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()

if __name__ == '__main__':
    main()
