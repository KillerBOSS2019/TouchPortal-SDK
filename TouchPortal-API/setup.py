from setuptools import setup, find_packages
 
classifiers = [
  'Development Status :: 5 - Production/Stable',
  'Intended Audience :: Education',
  'Operating System :: Microsoft :: Windows :: Windows 10',
  'License :: OSI Approved :: MIT License',
  'Programming Language :: Python :: 3'
]
 
setup(
  name='TouchPortal API',
  version='1.0.1',
  description='Touch Portal API for Python',
  long_description=open('README.txt').read() + '\n\n' + open('CHANGELOG.txt').read(),
  url='https://github.com/KillerBOSS2019/TouchPortal-API',  
  author='Damien',
  author_email='DamienWeiFen@gmail.com',
  license='MIT', 
  classifiers=classifiers,
  keywords='TouchPortal API', 
  packages=find_packages(),
  install_requires=[
      'pyee',
      'requests'
      ] 
)
