import asyncio
import humphrey
import json
import pathlib
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
    def post_message(token, channel, text, username):
        method = 'chat.postMessage'
        params = {'token': token, 'channel': channel, 'text': text,
                  'username': username}
        return Slack.call(method, params)


def on_action(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    target = tokens[2]
    if bot.is_irc_channel(target):
        source = tokens[0].lstrip(':')
        nick, _, _ = bot.parse_hostmask(source)
        text = ' '.join(tokens[4:])
        slack_channel = bot.c['channel_map'][target]
        Slack.post_message(token, slack_channel, text, nick)


def on_join(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    source = tokens[0].lstrip(':')
    nick, user, host = bot.parse_hostmask(source)
    irc_channel = tokens[2].lstrip(':')
    slack_channel = bot.c['channel_map'][irc_channel]
    text = '_joined {}_ [{}@{}]'.format(irc_channel, user, host)
    Slack.post_message(token, slack_channel, text, nick)


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
        Slack.post_message(token, slack_channel, text, old_nick)


def on_privmsg(message, bot):
    token = bot.c['slack:token']
    tokens = message.split()
    target = tokens[2]
    source = tokens[0].lstrip(':')
    nick, _, _ = bot.parse_hostmask(source)
    text = message.split(' :', maxsplit=1)[1]
    if bot.is_irc_channel(target):
        slack_channel = bot.c['channel_map'][target]
        Slack.post_message(token, slack_channel, text, nick)


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
        Slack.post_message(token, slack_channel, text, nick)


def on_rpl_endofmotd(_, bot):
    if 'irc:nickservpass' in bot.c:
        bot.send_privmsg('nickserv', 'identify ' + bot.c['irc:nickservpass'])
    for channel in bot.c['channel_map']:
        bot.out('JOIN ' + channel)


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

    loop = asyncio.get_event_loop()
    host = irc.c.get('irc:host')
    port = irc.c.get('irc:port')
    coro = loop.create_connection(irc, host, port)
    loop.run_until_complete(coro)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()

if __name__ == '__main__':
    main()
