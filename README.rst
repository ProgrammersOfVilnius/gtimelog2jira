.. default-role:: literal

Synchronize gTimeLog to Jira
############################

.. image:: https://github.com/ProgrammersOfVilnius/gtimelog2jira/workflows/build/badge.svg?branch=master
    :target: https://github.com/ProgrammersOfVilnius/gtimelog2jira/actions


This simple script will read your `timelog.txt` file populated by gtimelog_ and will submit work log
entries to Jira, via `Jira API`_.


Usage
=====

In order to synchronize your most recent entries to Jira, simply run::

  gtimelog2jira

By default, this command will synchronize entries created 7 days ago up to now.

You can control what time period you want to synchronize using the `--since`
parameter::

  gtimelog2jira --since 2000-01-01

You can also synchronize all entries of a single issue::

  gtimelog2jira --issue FOO-007

When `--issue` is specified and `--since` is not provided, the script will look all
entries containing the specified issue ID since the beginning.

If you want to limit the time interval, specify `--since`.

If you want to test things, without creating work log entries on Jira, you
can use the `--dry-run` flag::

  gtimelog2jira --dry-run

This way nothing will be sent to Jira, the script will instead show what it would do.


Configuration
=============

By default, `gtimelog2jira` reads configuration from the `~/.gtimelog/gtimelogrc`
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

  [gtimelog2jira:aliases]
  # catch-all issue for all billed work not attributable to a specific ticket
  FOO-MISC = FOO-1234

If the password is not specified, script will prompt to enter password
interactively.  (If you also have the python-keyring package installed, the
password will be remembered in your system keyring so you will not have to
enter it again.)

`projects` option should list all project prefixes. These prefixes will be used
to identify Jira issue IDs. If the script does not find anything that looks like
a Jira ID, it will skip that entry.


TODO
====

- Pagination is not supported when reading existing worklogs from Jira.

- Script does not handle situations when timelog.txt or Jira worklog entries are
  modified manually. The script simply checks if existing Jira worklog entries
  overlap the time ranges of timelog.txt entries, and if not, then new worklog
  entries are created. If there is an overlap, then entries are not created,
  even if the overlap is not exact.


.. _gtimelog: https://gtimelog.org/
.. _Jira API: https://docs.atlassian.com/software/jira/docs/api/REST/7.12.0/
