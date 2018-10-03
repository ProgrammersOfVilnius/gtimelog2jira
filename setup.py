from setuptools import setup, find_packages


setup(
    name="gtimelog2jira",
    version='0.1',
    description="Script to create Jira worklog entries from Gtimelog journal.",
    license='GPL',
    packages=find_packages(),
    install_requires=[
        'requests',
    ],
    entry_points={
        'console_scripts': [
            'gtimelog2jira=gtimelog2jira:main',
        ],
    },
)
