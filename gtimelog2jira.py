#!/usr/bin/env python3
import argparse
import collections
import configparser
import datetime
import getpass
import itertools
import operator
import pathlib
import re
import sys
import urllib.parse
from typing import Dict, Iterable

import keyring
import requests
from keyring.errors import NoKeyringError

assert sys.version_info >= (3, 7), "You need Python 3.7 or newer"


Entry = collections.namedtuple('Entry', ('start', 'end', 'message'))
JiraWorkLog = collections.namedtuple('JiraWorkLog', ('id', 'start', 'end'))
JiraSyncStatus = collections.namedtuple('JiraSyncStatus', ('entry', 'json', 'action'))


class WorkLog:

    def __init__(self, entry: Entry, issue: str, comment: str) -> None:
        self.entry = entry
        self.start = entry.start
        self.end = entry.end
        self.seconds = int((entry.end - entry.start).total_seconds())
        self.issue = issue
        self.comment = comment

    def __repr__(self):
        return '<WorkLog: %s, %s>' % (self.issue, self.comment)

    def __eq__(self, other):
        if not isinstance(other, WorkLog):
            return NotImplemented
        return (self.entry, self.issue, self.comment) == (other.entry, other.issue, other.comment)


class ConfigurationError(Exception):
    pass


def read_config(config_file: pathlib.Path) -> dict:
    if not config_file.exists():
        raise ConfigurationError("Configuration file %s does not exist." % config_file)

    config = configparser.ConfigParser()
    config.optionxform = str  # do not lowercase the aliases section!
    config.read(config_file)

    if not config.has_section('gtimelog2jira'):
        raise ConfigurationError("Section [gtimelog2jira] is not present in %s config file." % config_file)

    url = config.get('gtimelog2jira', 'jira')
    username = config.get('gtimelog2jira', 'username')
    password = config.get('gtimelog2jira', 'password')
    timelog = config.get('gtimelog2jira', 'timelog')
    jiralog = config.get('gtimelog2jira', 'jiralog')
    projects = config.get('gtimelog2jira', 'projects')
    include = config.get('gtimelog2jira', 'include', fallback='')
    midnight = config.get('gtimelog', 'virtual_midnight', fallback='06:00')

    if not url:
        raise ConfigurationError("Jira URL is not specified, set Jira URL via gtimelog2jira.jira setting.")

    if not username:
        raise ConfigurationError("Jira username is not specified, set Jira username via gtimelog2jira.username setting.")

    if not projects:
        raise ConfigurationError("List of projects is not specified, set Jira projects via gtimelog2jira.projects setting.")

    projects = set(projects.split())

    if config.has_section('gtimelog2jira:aliases'):
        aliases = dict(config.items('gtimelog2jira:aliases'))
    else:
        aliases = {}

    include = set(aliases.get(issue, issue) for issue in include.split())

    if not timelog:
        timelog = config_file.parent / 'timelog.txt'

    timelog = pathlib.Path(timelog).expanduser().resolve()
    if not timelog.exists():
        raise ConfigurationError("Timelog file %s does not exist." % timelog)

    jiralog = pathlib.Path(jiralog).expanduser().resolve()
    try:
        jiralog.open('a').close()
    except OSError as e:
        raise ConfigurationError("Jira log file %s is not writable: %s." % (jiralog, e))

    if not url.endswith('/'):
        url += '/'

    api = url + 'rest/api/2'

    session = requests.Session()

    if not password:
        try:
            password = keyring.get_password(url, username)
        except NoKeyringError as err:
            print("keyring:", err)

    attempts = range(3)
    for attempt in attempts:
        if attempt > 0 or not password:
            password = getpass.getpass('Enter Jira password for %s at %s: ' % (username, url))
            try:
                keyring.set_password(url, username, password)
            except NoKeyringError:
                print("Failed to save the password in the system keyring.")
            else:
                print("Saved the password in the system keyring.")
        session.auth = (username, password)
        resp = session.get('%s/myself' % api)
        if resp.ok:
            break
        elif resp.status_code == 401:
            try:
                keyring.delete_password(url, username)
            except NoKeyringError:
                pass
            else:
                print("Removed the saved incorrect password from the system keyring.")
            raise ConfigurationError("Error: Incorrect password or username.")
        elif resp.status_code == 403:
            raise ConfigurationError(
                "Jira credentials seems to be correct, but this user does "
                "not have permission to log in.\nTry to log in via browser, "
                "maybe you need to answer a security question: %s" % url
            )
        else:
            raise ConfigurationError("Something went wrong, Jira gave %s status code." % resp.status_code)

    return {
        'url': url,
        'api': api,
        'credentials': (username, password),
        'self': resp.json(),
        'timelog': timelog,
        'jiralog': jiralog,
        'projects': projects,
        'include': include,
        'aliases': aliases,
        'session': session,
        'midnight': midnight,
    }


def read_timelog(f: Iterable[str], midnight='06:00', tz=None) -> Iterable[Entry]:
    last = None
    nextday = None
    hour, minute = map(int, midnight.split(':'))
    midnight = {'hour': hour, 'minute': minute}
    day = datetime.timedelta(days=1)
    entries = 0
    last_note = None
    for line in f:
        line = line.strip()
        if line == '':
            continue

        try:
            time, note = line.split(': ', 1)
            time = datetime.datetime.strptime(time, '%Y-%m-%d %H:%M').astimezone()
        except ValueError:
            continue

        if nextday is None or time >= nextday:
            if last is not None and entries == 0:
                yield Entry(last, last, last_note)
            entries = 0
            last = time
            last_note = note
            nextday = time.replace(**midnight)
            if time >= nextday:
                nextday += day
            continue

        yield Entry(last, time, note)

        entries += 1
        last = time
        last_note = note

    if last is not None and entries == 0:
        yield Entry(last, last, last_note)


def parse_timelog(
    entries: Iterable[Entry],
    projects: Iterable[str],
    aliases: Dict[str, str],
    include: Iterable[str],
) -> Iterable[WorkLog]:
    # Python's | operator prefers the leftmost branch instead of the longest possible match.
    # This is documented in https://docs.python.org/3/library/re.html#regular-expression-syntax
    sorted_aliases = sorted(aliases, key=len, reverse=True)
    issue_re = re.compile(r'\b(?:%s)\b' % '|'.join(
        [r'(?:%s)-\d+' % '|'.join(projects)] + sorted_aliases
    ))
    include = set(include)

    for entry in entries:
        # Skip all non-work related entries.
        if entry.message.endswith('**'):
            continue

        # Find first suitable Jira issue id or skip entry.
        for match in issue_re.finditer(entry.message):
            issue = match.group()
            # Resolve aliases
            issue = aliases.get(issue, issue)
            # Apply include list
            if not include or issue in include:
                break
        else:
            continue

        # Clean up comment from categories and from issue id.
        comment = entry.message.rsplit(':', 1)[-1].strip()
        if comment.startswith(issue):
            comment = comment[len(issue):].strip()
        if comment.endswith(issue):
            comment = comment[:-len(issue)].strip()

        worklog = WorkLog(entry, issue, comment)
        if worklog.seconds > 0:
            yield worklog


def get_now():
    return datetime.datetime.now().astimezone()


def filter_timelog(entries: Iterable[WorkLog], *, since=None, until=None, issue=None) -> Iterable[WorkLog]:
    if since is None and issue is None:
        since = get_now() - datetime.timedelta(days=7)

    for entry in entries:
        if since and entry.start < since:
            continue
        if until and entry.end > until:
            continue
        if issue and entry.issue != issue:
            continue
        yield entry


def get_jira_worklog(session, api_url, issue, author_id=None) -> Iterable[JiraWorkLog]:
    resp = session.get(api_url + '/issue/' + issue + '/worklog')
    for worklog in resp.json().get('worklogs', []):
        if author_id and worklog['author']['accountId'] != author_id:
            continue
        started = datetime.datetime.strptime(worklog['started'], '%Y-%m-%dT%H:%M:%S.%f%z')
        ended = started + datetime.timedelta(seconds=worklog['timeSpentSeconds'])
        yield JiraWorkLog(worklog['id'], started, ended)


def sync_with_jira(session, api_url, entries: Iterable[WorkLog], dry_run=False, author_id=None) -> Iterable[JiraSyncStatus]:
    sort_key = operator.attrgetter('issue')
    entries = sorted(entries, key=sort_key)
    for issue, entries in itertools.groupby(entries, key=sort_key):
        worklog = list(get_jira_worklog(session, api_url, issue, author_id))
        for entry in entries:
            overlap = [x for x in worklog if x.start >= entry.start and x.end <= entry.end]
            if overlap:
                full_overlap = [x.id for x in overlap if x.start == entry.start and x.end == entry.end]
                partial_overlap = [x.id for x in overlap if x.start != entry.start or x.end != entry.end]
                resp = {
                    'id': ';'.join(full_overlap + partial_overlap),
                    'full': ';'.join(full_overlap),
                    'partial': ';'.join(partial_overlap),
                }
                yield JiraSyncStatus(entry, resp, 'overlap')
            elif dry_run:
                yield JiraSyncStatus(entry, {}, 'add (dry run)')
            else:
                resp = session.post(api_url + '/issue/' + issue + '/worklog', json={
                    'started': entry.start.strftime('%Y-%m-%dT%H:%M:%S.000%z'),
                    'timeSpentSeconds': entry.seconds,
                    'comment': entry.comment,
                })
                if resp.status_code >= 400:
                    yield JiraSyncStatus(entry, resp.json(), 'error')
                else:
                    yield JiraSyncStatus(entry, resp.json(), 'add')


def log_jira_sync(entries: Iterable[JiraSyncStatus], jiralog) -> Iterable[JiraSyncStatus]:
    with jiralog.open('a') as f:
        for entry, resp, action in entries:
            if action == 'error':
                comment = '; '.join(resp.get('errorMessages', []))
            else:
                comment = entry.comment
            f.write(','.join(map(str, [
                get_now().isoformat(timespec='seconds'),
                entry.start.isoformat(timespec='minutes'),
                entry.seconds,
                entry.issue,
                resp.get('id', ''),
                action,
                comment,
            ])) + '\n')

            yield JiraSyncStatus(entry, resp, action)


class Date:

    def __init__(self, fmt='%Y-%m-%d'):
        self.fmt = fmt

    def __call__(self, value):
        if value.lower() == 'today':
            return datetime.datetime.now().astimezone().replace(
                hour=0, minute=0, second=0, microsecond=0)
        if value.lower() == 'yesterday':
            return (datetime.datetime.now() - datetime.timedelta(1)).astimezone().replace(
                hour=0, minute=0, second=0, microsecond=0)
        return datetime.datetime.strptime(value, self.fmt).astimezone()


def human_readable_time(r: float, cols=False) -> str:
    fmt = '%2s%s' if cols else '%s%s'
    periods = [
        (60, 's'),
        (60, 'm'),
        (24, 'h'),
        (7, 'd'),
        (0, 'w'),
    ]
    result = []
    for d, u in periods:
        r, v = divmod(r, d) if d else (0, r)
        result += [fmt % (v, u)] if v else []
    return ' '.join(reversed(result))


def build_issue_url(jira_url, issue_number):
    return urllib.parse.urljoin(jira_url, 'browse/' + issue_number)


def show_results(entries: Iterable[JiraSyncStatus], stdout, jira_url, aliases: Dict[str, str], verbose=0):
    totals = {
        'seconds': collections.defaultdict(int),
        'entries': collections.defaultdict(int),
        'overlap_seconds': collections.defaultdict(int),
        'overlap_entries': collections.defaultdict(int),
        'partial_overlap_seconds': collections.defaultdict(int),
        'partial_overlap_entries': collections.defaultdict(int),
    }
    reverse_aliases = {v: k for k, v in aliases.items()}

    print(file=stdout)

    for entry, resp, action in entries:
        action = action.replace(' (dry run)', '')
        if action == 'add':
            print('ADD: {issue:<10} {start} {amount:>8}: {comment}'.format(
                issue=entry.issue,
                start=entry.start.isoformat(timespec='minutes'),
                amount=human_readable_time(entry.seconds, cols=True),
                comment=entry.comment,
            ), file=stdout)
            totals['seconds'][entry.issue] += entry.seconds
            totals['entries'][entry.issue] += 1
        elif action == 'error':
            print('ERR: {issue:<10} {start} {amount:>8}: {comment}'.format(
                issue=entry.issue,
                start=entry.start.isoformat(timespec='minutes'),
                amount=human_readable_time(entry.seconds, cols=True),
                comment='; '.join(resp.get('errorMessages', [])),
            ), file=stdout)
        elif action == 'overlap':
            if verbose >= 1:
                print('OVR: {issue:<10} {start} {amount:>8}: {comment}'.format(
                    issue=entry.issue,
                    start=entry.start.isoformat(timespec='minutes'),
                    amount=human_readable_time(entry.seconds, cols=True),
                    comment=entry.comment,
                ), file=stdout)
            if resp['full'] and verbose >= 2:
                print('     full overlap with {}'.format(resp['full']), file=stdout)
            if resp['partial'] and verbose >= 2:
                print('     partial overlap with {}'.format(resp['partial']), file=stdout)
            totals['overlap_seconds'][entry.issue] += entry.seconds
            totals['overlap_entries'][entry.issue] += 1
            if resp['partial']:
                totals['partial_overlap_seconds'][entry.issue] += entry.seconds
                totals['partial_overlap_entries'][entry.issue] += 1

    if totals['seconds']:
        print(file=stdout)
        print('TOTALS:', file=stdout)
        for issue, seconds in sorted(totals['seconds'].items()):
            entries = totals['entries'][issue]
            issue_url = build_issue_url(jira_url, issue)
            alias = reverse_aliases.get(issue, '')
            time_spent = human_readable_time(seconds, cols=True)
            print(
                '%10s: %8s (%s), %s%s'
                % (issue, time_spent, entries, issue_url, alias and f' ({alias})'),
                file=stdout,
            )
    if totals['overlap_seconds'] and verbose >= 1:
        print(file=stdout)
        print('TOTAL OVERLAP:', file=stdout)
        for issue, seconds in sorted(totals['overlap_seconds'].items()):
            entries = totals['overlap_entries'][issue]
            issue_url = build_issue_url(jira_url, issue)
            alias = reverse_aliases.get(issue, '')
            time_spent = human_readable_time(seconds, cols=True)
            print(
                '%10s: %8s (%s), %s%s'
                % (issue, time_spent, entries, issue_url, alias and f' ({alias})'),
                file=stdout,
            )
    if totals['partial_overlap_seconds']:
        print(file=stdout)
        print('WARNING!  Some entries had partial overlap with existing entries and were skipped:', file=stdout)
        for issue, seconds in sorted(totals['partial_overlap_seconds'].items()):
            entries = totals['partial_overlap_entries'][issue]
            issue_url = build_issue_url(jira_url, issue)
            alias = reverse_aliases.get(issue, '')
            time_spent = human_readable_time(seconds, cols=True)
            print(
                '%10s: %8s (%s), %s%s'
                % (issue, time_spent, entries, issue_url, alias and f' ({alias})'),
                file=stdout,
            )


def _main(argv=None, stdout=sys.stdout):
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', default='~/.gtimelog/gtimelogrc')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='be more verbose (can be repeated)')
    parser.add_argument('--dry-run', action='store_true', default=False,
                        help="don't sync anything, just show what would be done")
    parser.add_argument('--since', type=Date(), help="sync logs from specfied yyyy-mm-dd date")
    parser.add_argument('--until', type=Date(), help="sync logs up until specfied yyyy-mm-dd date")
    parser.add_argument('--issue', help="sync only specified issue number")
    args = parser.parse_args(argv)

    if args.since and args.until and args.since >= args.until:
        parser.error(
            'the time interval is empty ({args.since} .. {args.until})'.format(
                args=args))

    config_file = pathlib.Path(args.config).expanduser().resolve()
    try:
        config = read_config(config_file)
    except ConfigurationError as e:
        print('Error:', e, file=stdout)
        return 1

    with config['timelog'].open() as f:
        entries = read_timelog(f, midnight=config['midnight'])
        entries = parse_timelog(entries, config['projects'], config['aliases'], config['include'])
        entries = filter_timelog(entries, since=args.since, until=args.until,
                                 issue=config['aliases'].get(args.issue, args.issue))
        entries = sync_with_jira(config['session'], config['api'], entries, dry_run=args.dry_run,
                                 author_id=config['self']['accountId'])
        entries = log_jira_sync(entries, config['jiralog'])
        show_results(entries, stdout, config['url'], config['aliases'], verbose=args.verbose)


def main(argv=None, stdout=sys.stdout):
    try:
        _main(argv=argv, stdout=stdout)
    except KeyboardInterrupt:
        sys.exit("Interrupted!")


if __name__ == '__main__':
    sys.exit(main())
