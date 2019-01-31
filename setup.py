from setuptools import setup


setup(
    name="gtimelog2jira",
    version='0.1',
    description="Script to create Jira worklog entries from Gtimelog journal.",
    license='GPL',
    py_modules=['gtimelog2jira'],
    install_requires=[
        'requests',
    ],
    extras_require={
        'keyring': [
            'keyring',
        ],
    },
    entry_points={
        'console_scripts': [
            'gtimelog2jira=gtimelog2jira:main',
        ],
    },
)
