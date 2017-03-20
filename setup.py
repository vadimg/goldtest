from distutils.core import setup
setup(
    name='goldtest',
    packages=['goldtest'],  # this must be the same as the name above
    version='0.1',
    description='Automagically generate tests to verify API responses or DB state.',
    author='Vadim Graboys',
    author_email='dimva13@gmail.com',
    url='https://github.com/vadimg/goldtest',
    download_url='https://github.com/vadimg/goldtest/tarball/0.1',
    keywords=['goldtest', 'gold', 'test', 'testing'],
    classifiers=[],
    install_requires=[
        'sqlalchemy>=0.9.8',
        'pytz',
    ]
)
