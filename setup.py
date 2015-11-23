from setuptools import find_packages, setup

setup(
    name='slirck',
    version='0.1',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'slirck = slirck.slirck:main'
        ]
    }
)
