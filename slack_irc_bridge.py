import aiohttp.web
import asyncio
import humphrey
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request


def send_to_slack(text, username, bot):
    url = bot.c.get('slack:url')
    params = {'text': text, 'username': '<{}>'.format(username)}
    avatar = get_rw_avatar_url(username, bot)
    if avatar is not None:
        params['icon_url'] = avatar
    data = json.dumps(params).encode()
    urllib.request.urlopen(url, data=data)


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


def on_rpl_endofmotd(_, bot):
    bot.out('JOIN {}'.format(bot.c.get('irc:channel')))


def on_join(message, bot):
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, user, host = bot.parse_hostmask(source)
    channel = tokens[2].lstrip(':')
    m = '*{}* joined *{}* [{}@{}]'.format(nick, channel, user, host)
    send_to_slack(m, bot.c['irc:host'], bot)


def on_quit(message, bot):
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, user, host = bot.parse_hostmask(source)
    text = message.split(' :', maxsplit=1)[1]
    send_to_slack('*{}* quit [{}]'.format(nick, text), bot.c['irc:host'], bot)


def on_nick(message, bot):
    tokens = message.split()
    source = tokens[0].lstrip(':')
    old_nick, _, _ = bot.parse_hostmask(source)
    new_nick = tokens[2].lstrip(':')
    m = '*{}* is now known as *{}*'.format(old_nick, new_nick)
    send_to_slack(m, bot.c['irc:host'], bot)


def on_privmsg(message, bot):
    tokens = message.split()
    target = tokens[2]
    source = tokens[0].lstrip(':')
    source_nick, _, _ = bot.parse_hostmask(source)
    text = message.split(' :', maxsplit=1)[1]
    if bot.is_irc_channel(target):
        send_to_slack(text, source_nick, bot)


def on_action(message, bot):
    tokens = message.split()
    target = tokens[2]
    if bot.is_irc_channel(target):
        source = tokens[0].lstrip(':')
        nick, _, _ = bot.parse_hostmask(source)
        text = ' '.join(tokens[4:])
        send_to_slack('_{}_'.format(text), nick, bot)


def main():
    config_file = pathlib.Path(__file__).resolve().with_name('_config.json')
    irc = humphrey.IRCClient(config_file)
    irc.c.pretty = True
    irc.debug = True

    irc.ee.on('376', func=on_rpl_endofmotd)
    irc.ee.on('ACTION', func=on_action)
    irc.ee.on('JOIN', func=on_join)
    irc.ee.on('NICK', func=on_nick)
    irc.ee.on('PRIVMSG', func=on_privmsg)
    irc.ee.on('QUIT', func=on_quit)

    def receive_from_slack(request):
        data = yield from request.content.read()
        data = urllib.parse.parse_qs(data.decode())
        if 'USLACKBOT' in data['user_id']:
            return aiohttp.web.Response()

        speaker = data['user_name'][0]
        text = data['text'][0]
        irc.log('## Passing message from Slack to IRC')
        irc.send_privmsg(irc.c['irc:channel'], '<{}> {}'.format(speaker, text))
        return aiohttp.web.Response()

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
