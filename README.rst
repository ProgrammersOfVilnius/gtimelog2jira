.. default-role:: literal

Synchronize gTimeLog to Jira
############################

This simple script will read your `timelog.txt` file populated by gtimelog_ and will submit work log
entries to Jira, via `Jira API`_.


Usage
=====

In order to synchronize your most recent entries to Jira, simply run::

  gtimelog2jira

By default, this command will sinchronize entries created 7 days ago up to now.

You can control what time period you want to synchronize using `--since`
parametery::

  gtimelog2jira --since 2000-01-01

You can also synchronize all entries of single issue::

  gtimelog2jira --issue FOO-007

When `--issue` is specified and `--since` is not provided, script will look all
entries containing specified issue id since the begining.

If you want to limit time interval, specify `--since`.

If you want to just test things, without creating work log entries on Jira, you
can use `--dry-run` flag::

  gtimelog2jira --dry-run

This way, nothing will be sent to Jira, script just shows what it would do.


Configuration
=============

By default, `gtimelog2jira` reads configuration from `~/.gtimelog/gtimelogrc`
file. Configuration file example:

.. code-block:: ini

  [gtimelog2jira]
  jira = https://jira.example.com/
  username = me@example.com
  password =
  timelog = ~/.gtimelog/timelog.txt
  jiralog = ~/.gtimelog/jira.log
  projects =
    FOO
    BAR
    BAZ

If password is not specified, script will prompt to enter password
interactively.

`projects` option should list all project prefixes. These prefixes will be used
to identify Jira issue ids. If script does not find anything that looks like
Jira id, it will skip that entry.


TODO
====

- Pagination is not supported when reading existing worklogs from Jira.

- Script does not handle situations when timelog or Jira worklog entries are
  modified manualy. Script simply checks if existing Jira worklog entries does
  not overlap if not, then worklog entries are created. If there is an overlap,
  then entries are not created.


.. _gtimelog: https://gtimelog.org/
.. _Jira API: https://docs.atlassian.com/software/jira/docs/api/REST/7.12.0/
