from setuptools import setup

setup(
    name='abap',
    version='0.1.0',
    description='',
    author='Naglis Jonaitis',
    author_email='naglis@mailbox.org',
    license='MIT',
    packages=['abap'],
    install_requires=[
        'tornado>=4.4.0,<4.5.0',
        'mutagen>=1.36.0,<1.37.0',
        'attrs>=16.3.0,<17.0.0',
    ],
    entry_points={
        'console_scripts': ['abap = abap.main:main'],
    },
    include_package_data=True,
    zip_safe=False
)
