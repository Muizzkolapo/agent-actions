




Does my operating system have prerequisites? \| dbt Developer Hub

















[Skip to main content](#docusaurus_skipToContent_fallback)[Join our biweekly demos and see dbt Cloud in action!](https://www.getdbt.com/resources/webinars/dbt-cloud-demos-with-experts/?utm_medium=internal&utm_source=docs&utm_campaign=q2-2025_biweekly-demos_aw&utm_content=biweekly-demos____&utm_term=all_all__)[![dbt Logo](/img/dbt-logo.svg)![dbt Logo](/img/dbt-logo-light.svg)](/)On this pageYour operating system may require pre\-installation setup before installing dbt Core with pip. After downloading and installing any dependencies specific to your development environment, you can proceed with the [pip installation of dbt Core](/docs/core/pip-install).

### CentOS[​](#centos "Direct link to CentOS")

CentOS requires Python and some other dependencies to successfully install and run dbt Core.

To install Python and other dependencies:


```
  
sudo yum install redhat-rpm-config gcc libffi-devel \  
  python-devel openssl-devel  
  

```
### MacOS[​](#macos "Direct link to MacOS")

The MacOS requires Python 3\.8 or higher to successfully install and run dbt Core.

To check the Python version:


```
  
python --version  
  

```
If you need a compatible version, you can download and install [Python version 3\.8 or higher for MacOS](https://www.python.org/downloads/macos).

If your machine runs on an Apple M1 architecture, we recommend that you install dbt via [Rosetta](https://support.apple.com/en-us/HT211861). This is necessary for certain dependencies that are only supported on Intel processors.

### Ubuntu/Debian[​](#ubuntudebian "Direct link to Ubuntu/Debian")

Ubuntu requires Python and other dependencies to successfully install and run dbt Core.

To install Python and other dependencies:


```
  
sudo apt-get install git libpq-dev python-dev python3-pip  
sudo apt-get remove python-cffi  
sudo pip install --upgrade cffi  
pip install cryptography~=3.4  
  

```
### Windows[​](#windows "Direct link to Windows")

Windows requires Python and git to successfully install and run dbt Core.

Install [Git for Windows](https://git-scm.com/downloads) and [Python version 3\.8 or higher for Windows](https://www.python.org/downloads/windows/).

For further questions, please see the [Python compatibility FAQ](/faqs/Core/install-python-compatibility)

0* [CentOS](#centos)
* [MacOS](#macos)
* [Ubuntu/Debian](#ubuntudebian)
* [Windows](#windows)

[Edit this page](https://github.com/dbt-labs/docs.getdbt.com/edit/current/website/docs/faqs/Core/install-pip-os-prereqs.md)





## Link
https://docs.getdbt.com/faqs/Core/install-pip-os-prereqs.md