from setuptools import setup, find_packages

setup(
    name="telegram-bot",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "python-telegram-bot>=20.0",
        "apscheduler>=3.10.0",
        "pillow>=10.0.0", 
        "flask>=2.0.0"
    ],
)
