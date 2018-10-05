import configparser
import datetime
import io
import itertools
import pathlib
import re
import os

import pytest
import requests_mock

import gtimelog2jira


os.environ['TZ'] = 'Europe/Vilnius'


class Route:

    def __init__(self, handler, params=None):
        self.handler = handler
        self.params = params or {}
        self.pattern = None


class JiraApi:

    def __init__(self, mock, user='User Name'):
        self.mock = mock
        self.url = 'https://jira.example.com'
        self.base = '/rest/api/2'
        self.idseq = map(str, itertools.count(1))
        self.dtformat = '%Y-%m-%dT%H:%M:%S.000%z'
        self.routes = {
            'get /myself': Route(self.myself),
            'get /issue/{issue}/worklog': Route(self.list_worklog, {
                'issue': r'[A-Z]+-[0-9]+',
            }),
            'post /issue/{issue}/worklog': Route(self.create_worklog, {
                'issue': r'[A-Z]+-[0-9]+',
            }),
        }

        for key, route in self.routes.items():
            method, path = key.split(None, 1)
            route.pattern = re.compile(self.base + path.format(**{
                k: '(?P<%s>%s)' % (k, v)
                for k, v in route.params.items()
            }))
            self.mock.register_uri(method, route.pattern, json=route.handler)

        self.db = {
            'user': user,
            'issues': {
                'BAR-24': {'issueId': next(self.idseq), 'worklog': {}},
                'FOO-42': {'issueId': next(self.idseq), 'worklog': {}},
                'FOO-64': {'issueId': next(self.idseq), 'worklog': {}},
            },
        }

        self._add_worklog('Someone Else', 'FOO-64', datetime.datetime(2014, 4, 16, 11, 0).astimezone(), 300,
                          'did some work')

    def _get_url_params(self, request, name):
        return self.routes[name].pattern.search(request.url).groups()

    def _get_user(self, name=None):
        name = name or self.db['user']
        username = name.lower().replace(' ', '.') + '@example.com'
        return {
            'active': True,
            'displayName': name,
            'emailAddress': username,
            'key': username,
            'name': username,
            'self': self.url + self.base + '/user?username' + username,
            'timeZone': 'Europe/Helsinki',
        }

    def _add_worklog(self, user, issue, started, seconds, comment):
        now = datetime.datetime.now()
        worklog_id = next(self.idseq)
        self.db['issues'][issue]['worklog'][worklog_id] = {
            'id': worklog_id,
            'author': self._get_user(user),
            'comment': comment,
            'started': started if isinstance(started, str) else started.strftime(self.dtformat),
            'timeSpent': gtimelog2jira.human_readable_time(seconds),
            'timeSpentSeconds': seconds,
            'created': now.strftime(self.dtformat),
            'updated': now.strftime(self.dtformat),
        }
        return worklog_id

    def myself(self, request, context):
        context.headers['content-type'] = 'application/json'

        return {
            'locale': 'lt_LT',
            **self._get_user()
        }

    def list_worklog(self, request, context):
        context.headers['content-type'] = 'application/json'
        issue, = self._get_url_params(request, 'get /issue/{issue}/worklog')

        if issue not in self.db['issues']:
            context.status_code = 404
            return {
                'errorMessages': ['Issue ' + issue + ' Does Not Exist'],
                'errors': {},
            }

        else:
            total = len(self.db['issues'][issue]['worklog'])
            return {
                'maxResults': total,
                'startAt': 0,
                'total': total,
                'worklogs': [worklog for worklog in self.db['issues'][issue]['worklog'].values()],
            }

    def create_worklog(self, request, context):
        context.headers['content-type'] = 'application/json'
        issue, = self._get_url_params(request, 'post /issue/{issue}/worklog')

        if issue not in self.db['issues']:
            context.status_code = 404
            return {
                'errorMessages': ['Issue ' + issue + ' Does Not Exist'],
                'errors': {},
            }

        else:
            context.status_code = 201
            data = request.json()
            worklog_id = self._add_worklog(self.db['user'], issue, data['started'], data['timeSpentSeconds'],
                                           data['comment'])
            worklog = self.db['issues'][issue]['worklog'][worklog_id]
            return {
                'author': worklog['author'],
                'comment': worklog['comment'],
                'created': worklog['created'],
                'id': worklog_id,
                'issueId': self.db['issues'][issue]['issueId'],
                'self': self.url + self.base + '/issue/' + self.db['issues'][issue]['issueId'] + '/worklog/' + worklog_id,
                'started': worklog['started'],
                'timeSpent': worklog['timeSpent'],
                'timeSpentSeconds': worklog['timeSpentSeconds'],
                'updateAuthor': worklog['author'],
                'updated': worklog['created'],
            }


class Env:

    def __init__(self, path, mocker, jira):
        self.stdout = None
        self.path = pathlib.Path(path)
        self.gtimelogrc = path / 'gtimelogrc'
        self.timelog = path / 'timelog.txt'
        self.jiralog = path / 'jira.log'
        self.jira = jira

        mocker.patch('getpass.getpass', return_value='secret')

        config = configparser.ConfigParser()
        config.read_dict({
            'gtimelog2jira': {
                'jira': 'https://jira.example.com/',
                'username': 'me@example.com',
                'password': '',
                'timelog': str(self.timelog),
                'jiralog': str(self.jiralog),
                'projects': 'FOO BAR BAZ',
            }
        })
        with self.gtimelogrc.open('w') as f:
            config.write(f)

        self.log([
            '2014-03-24 14:15: arrived',
            '2014-03-24 18:14: project1: some work',
            '',
            '2014-03-31 08:00: arrived'
            '2014-03-31 15:48: project1: FOO-42 some work',
            '2014-03-31 17:10: project2: ABC-1 some work',
            '2014-03-31 17:38: project1: BAR-24 some work',
            '2014-03-31 18:51: project1: FOO-42 some more work'
            '',
            '2014-04-01 13:54: arrived',
            '2014-04-01 15:41: project1: FOO-42 some work',
            '2014-04-01 16:04: tea **',
            '2014-04-01 18:00: project1: FOO-42 some more work',
            '',
            '2014-04-16 10:30: arrived',
            '2014-04-16 11:25: project1: FOO-64 initial work',
            '2014-04-16 12:30: project1: FOO-00 missing issue',
        ])

    def log(self, lines):
        with self.timelog.open('a') as f:
            for line in lines:
                f.write(line + '\n')

    def run(self, argv=None):
        self.stdout = io.StringIO()
        argv = ['-c', str(self.gtimelogrc)] + (argv or [])
        return gtimelog2jira.main(argv, self.stdout)

    def get_worklog(self):
        user = self.jira._get_user()
        return [
            (worklog['started'], worklog['timeSpentSeconds'], issue_id, worklog['comment'])
            for issue_id, issue in self.jira.db['issues'].items()
            for worklog_id, worklog in issue['worklog'].items()
            if worklog['author']['name'] == user['name']
        ]

    def get_jiralog(self):
        with self.jiralog.open() as f:
            return [tuple(line.strip().split(',', 7)[1:]) for line in f]

    def get_stdout(self):
        return self.stdout.getvalue().splitlines()


@pytest.yield_fixture
def env(tmpdir, mocker):
    with requests_mock.Mocker() as mock:
        jira = JiraApi(mock)
        yield Env(tmpdir, mocker, jira)


def test_no_args(env, mocker):
    mocker.patch('gtimelog2jira.get_now', return_value=datetime.datetime(2014, 4, 18).astimezone())
    assert env.run() is None
    env.log([
        '',
        '2014-04-17 10:30: arrived',
        '2014-04-17 11:25: project1: FOO-64 do more work',
    ])
    assert env.run() is None
    assert env.get_worklog() == [
        ('2014-04-16T10:30:00.000+0300', 3300, 'FOO-64', 'initial work'),
        ('2014-04-17T10:30:00.000+0300', 3300, 'FOO-64', 'do more work'),
    ]
    assert env.get_jiralog() == [
        ('2014-04-16T11:25+03:00', '3900', 'FOO-00', '', 'error', 'Issue FOO-00 Does Not Exist'),
        ('2014-04-16T10:30+03:00', '3300', 'FOO-64', '5', 'add', 'initial work'),
        ('2014-04-16T11:25+03:00', '3900', 'FOO-00', '', 'error', 'Issue FOO-00 Does Not Exist'),
        ('2014-04-16T10:30+03:00', '3300', 'FOO-64', '5', 'overlap', 'initial work'),
        ('2014-04-17T10:30+03:00', '3300', 'FOO-64', '6', 'add', 'do more work'),
    ]


def test_full_sync(env):
    assert env.run(['--since', '2014-01-01']) is None
    env.log([
        '',
        '2014-04-17 10:30: arrived',
        '2014-04-17 11:25: project1: FOO-64 do more work',
    ])
    assert env.run(['--since', '2014-01-01']) is None
    assert env.get_worklog() == [
        ('2014-03-31T17:10:00.000+0300', 1680, 'BAR-24', 'some work'),
        ('2014-03-31T17:38:00.000+0300', 4380, 'FOO-42', 'some more work'),
        ('2014-04-01T13:54:00.000+0300', 6420, 'FOO-42', 'some work'),
        ('2014-04-01T16:04:00.000+0300', 6960, 'FOO-42', 'some more work'),
        ('2014-04-16T10:30:00.000+0300', 3300, 'FOO-64', 'initial work'),
        ('2014-04-17T10:30:00.000+0300', 3300, 'FOO-64', 'do more work'),
    ]
    assert env.get_jiralog() == [
        ('2014-03-31T17:10+03:00', '1680', 'BAR-24', '5', 'add', 'some work'),
        ('2014-04-16T11:25+03:00', '3900', 'FOO-00', '', 'error', 'Issue FOO-00 Does Not Exist'),
        ('2014-03-31T17:38+03:00', '4380', 'FOO-42', '6', 'add', 'some more work'),
        ('2014-04-01T13:54+03:00', '6420', 'FOO-42', '7', 'add', 'some work'),
        ('2014-04-01T16:04+03:00', '6960', 'FOO-42', '8', 'add', 'some more work'),
        ('2014-04-16T10:30+03:00', '3300', 'FOO-64', '9', 'add', 'initial work'),
        ('2014-03-31T17:10+03:00', '1680', 'BAR-24', '5', 'overlap', 'some work'),
        ('2014-04-16T11:25+03:00', '3900', 'FOO-00', '', 'error', 'Issue FOO-00 Does Not Exist'),
        ('2014-03-31T17:38+03:00', '4380', 'FOO-42', '6', 'overlap', 'some more work'),
        ('2014-04-01T13:54+03:00', '6420', 'FOO-42', '7', 'overlap', 'some work'),
        ('2014-04-01T16:04+03:00', '6960', 'FOO-42', '8', 'overlap', 'some more work'),
        ('2014-04-16T10:30+03:00', '3300', 'FOO-64', '9', 'overlap', 'initial work'),
        ('2014-04-17T10:30+03:00', '3300', 'FOO-64', '10', 'add', 'do more work'),
    ]


def test_single_issue(env):
    assert env.run(['--issue', 'FOO-42']) is None
    env.log([
        '',
        '2014-04-17 10:30: arrived',
        '2014-04-17 11:25: project1: FOO-42 do more work',
        '2014-04-17 12:30: project1: FOO-64 do more work',
    ])
    assert env.run(['--issue', 'FOO-42']) is None
    assert env.get_worklog() == [
        ('2014-03-31T17:38:00.000+0300', 4380, 'FOO-42', 'some more work'),
        ('2014-04-01T13:54:00.000+0300', 6420, 'FOO-42', 'some work'),
        ('2014-04-01T16:04:00.000+0300', 6960, 'FOO-42', 'some more work'),
        ('2014-04-17T10:30:00.000+0300', 3300, 'FOO-42', 'do more work'),
    ]
    assert env.get_jiralog() == [
        ('2014-03-31T17:38+03:00', '4380', 'FOO-42', '5', 'add', 'some more work'),
        ('2014-04-01T13:54+03:00', '6420', 'FOO-42', '6', 'add', 'some work'),
        ('2014-04-01T16:04+03:00', '6960', 'FOO-42', '7', 'add', 'some more work'),
        ('2014-03-31T17:38+03:00', '4380', 'FOO-42', '5', 'overlap', 'some more work'),
        ('2014-04-01T13:54+03:00', '6420', 'FOO-42', '6', 'overlap', 'some work'),
        ('2014-04-01T16:04+03:00', '6960', 'FOO-42', '7', 'overlap', 'some more work'),
        ('2014-04-17T10:30+03:00', '3300', 'FOO-42', '8', 'add', 'do more work'),
    ]


def test_since_date(env):
    assert env.run(['--since', '2014-04-16']) is None
    assert env.run(['--since', '2014-04-16']) is None
    assert env.get_worklog() == [
        ('2014-04-16T10:30:00.000+0300', 3300, 'FOO-64', 'initial work')
    ]
    assert env.get_jiralog() == [
        ('2014-04-16T11:25+03:00', '3900', 'FOO-00', '', 'error', 'Issue FOO-00 Does Not Exist'),
        ('2014-04-16T10:30+03:00', '3300', 'FOO-64', '5', 'add', 'initial work'),
        ('2014-04-16T11:25+03:00', '3900', 'FOO-00', '', 'error', 'Issue FOO-00 Does Not Exist'),
        ('2014-04-16T10:30+03:00', '3300', 'FOO-64', '5', 'overlap', 'initial work'),
    ]


def test_dry_run(env):
    assert env.run(['--dry-run', '--since', '2014-01-01']) is None
    assert env.get_worklog() == []
    assert env.get_jiralog() == [
        ('2014-03-31T17:10+03:00', '1680', 'BAR-24', '', 'add (dry run)', 'some work'),
        ('2014-04-16T11:25+03:00', '3900', 'FOO-00', '', 'add (dry run)', 'missing issue'),
        ('2014-03-31T17:38+03:00', '4380', 'FOO-42', '', 'add (dry run)', 'some more work'),
        ('2014-04-01T13:54+03:00', '6420', 'FOO-42', '', 'add (dry run)', 'some work'),
        ('2014-04-01T16:04+03:00', '6960', 'FOO-42', '', 'add (dry run)', 'some more work'),
        ('2014-04-16T10:30+03:00', '3300', 'FOO-64', '', 'add (dry run)', 'initial work'),
    ]
    assert env.get_stdout() == [
        '',
        'ADD: BAR-24     2014-03-31T17:10+03:00      28m: some work',
        'ADD: FOO-00     2014-04-16T11:25+03:00   1h  5m: missing issue',
        'ADD: FOO-42     2014-03-31T17:38+03:00   1h 13m: some more work',
        'ADD: FOO-42     2014-04-01T13:54+03:00   1h 47m: some work',
        'ADD: FOO-42     2014-04-01T16:04+03:00   1h 56m: some more work',
        'ADD: FOO-64     2014-04-16T10:30+03:00      55m: initial work',
        '',
        'TOTALS:',
        '    BAR-24:      28m (1), https://jira.example.com/browse/BAR-24',
        '    FOO-00:   1h  5m (1), https://jira.example.com/browse/FOO-00',
        '    FOO-42:   4h 56m (3), https://jira.example.com/browse/FOO-42',
        '    FOO-64:      55m (1), https://jira.example.com/browse/FOO-64',
    ]
