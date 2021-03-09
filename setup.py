from setuptools import setup
from version import get_git_version

try:
    version = get_git_version()
    assert version is not None
except (AttributeError, AssertionError):
    version = '0.0.0'

setup(name='lwa-pyutils',
      version=version,
      url='http://github.com/ovro-lwa/lwa-pyutils',
      packages=['lwautils'],
      package_data = {
          'lwautils': ['conf/*'],
          },
      tests_require=[
          'coverage'
          ],
      entry_points='''
          [console_scripts]
      ''',      
      zip_safe=False)
