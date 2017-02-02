from setuptools import setup

setup(
    name='abook',
    version='0.1.0',
    description='',
    author='Naglis Jonaitis',
    author_email='naglis@mailbox.org',
    license='MIT',
    packages=['abook'],
    install_requires=[
        'tornado>=4.4.0,<4.5.0',
        'mutagen>=1.36.0,<1.37.0',
    ],
    entry_points={
        'console_scripts': ['abook = abook.main:main'],
    },
    include_package_data=True,
    zip_safe=False
)
