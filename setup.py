from setuptools import setup


setup(
    name="gtimelog2jira",
    version='0.1',
    description="Script to create Jira worklog entries from Gtimelog journal.",
    license='GPL',
    py_modules=['gtimelog2jira'],
    install_requires=[
        'requests',
        'keyring',
    ],
    entry_points={
        'console_scripts': [
            'gtimelog2jira=gtimelog2jira:main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    python_requires='>= 3.6',
)
