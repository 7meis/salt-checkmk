'''
Open Monitoring Distribution (OMD) Management Module

:maintainer: Philipp Lemke

:maturity: new

:depends: omd / checkmk

'''

import salt.exceptions
import errno
import subprocess
import logging
import os
import pty
import re
from datetime import datetime
from salt.exceptions import SaltException


__virtualname__ = 'omd'
OMD_BIN = '/usr/bin/omd'
LOGGER = logging.getLogger(__name__)


def __virtual__():
    if not os.path.isfile(OMD_BIN):
        return (False, 'The omd execution module cannot be loaded: {} is missing.'.format(OMD_BIN))
    if not os.access(OMD_BIN, os.X_OK):
        return (False, 'The omd execution module cannot be loaded: {} is not executable.'.format(OMD_BIN))
    return __virtualname__


def _check_site_config_value_exists(name, key):
    # This config keys won't be listed by omd config show
    # e.g. LIVESTATUS_TCP_PORT will be only displayed if LIVESTATUS_TCP is set
    # To prohibit errors the following list of keys will be ignored

    NO_CHECK_CONFIG_VALUES = ['LIVESTATUS_TCP_PORT', 'LIVESTATUS_TCP_TLS']

    if not (key in NO_CHECK_CONFIG_VALUES or site_config_value_exists(name, key)):
        raise salt.exceptions.CommandExecutionError("Config value [{}] does not exist.".format(key))

def _strip_ansi(value):
    if not isinstance(value, str):
        return value
    return re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', value)


def _format_log_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _build_update_log_entry(site, target_version, args, retcode, details, output, preserve_colors):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        '',
        '=' * 80,
        'timestamp: {}'.format(timestamp),
        'site: {}'.format(site),
        'target_version: {}'.format(target_version),
        'command: {}'.format(' '.join(args)),
        'retcode: {}'.format(retcode),
        'preserve_colors: {}'.format(_format_log_value(preserve_colors)),
        'details: {}'.format(details),
        '=' * 80,
    ]
    if output:
        lines.append('output:')
        lines.append(output.rstrip('\n'))
    return '\n'.join(lines) + '\n'


def _raise_command_error(args, retcode, stdout='', stderr=''):
    stdout_clean = _strip_ansi(stdout).strip()
    stderr_clean = _strip_ansi(stderr).strip()

    message_parts = [
        "Command '{cmd}' returned: {ret}".format(cmd=" ".join(args), ret=retcode)
    ]

    if stdout_clean:
        message_parts.append("STDOUT: {}".format(stdout_clean))
    if stderr_clean:
        message_parts.append("STDERR: {}".format(stderr_clean))
    if not stdout_clean and not stderr_clean:
        message_parts.append('No command output captured.')

    message = '. '.join(message_parts)
    raise salt.exceptions.CommandExecutionError(message)


def _exec_command_tty(args):
    if isinstance(args, str):
        args = args.split()

    env = os.environ.copy()
    env.setdefault('TERM', 'xterm-256color')
    master_fd, slave_fd = pty.openpty()
    output_chunks = []

    try:
        p = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
        )
        os.close(slave_fd)
        slave_fd = None

        while True:
            try:
                chunk = os.read(master_fd, 4096)
                if not chunk:
                    break
                output_chunks.append(chunk)
            except OSError as e:
                if e.errno == errno.EIO:
                    break
                raise

        retcode = p.wait()
    finally:
        os.close(master_fd)
        if slave_fd is not None:
            os.close(slave_fd)

    return b''.join(output_chunks).decode('utf-8', errors='replace'), retcode


def _exec_command(args, ignore_errors=False, stdin_data=None, use_tty=False, combine_stderr=False):
    if isinstance(args, str):
        args = args.split()

    if use_tty:
        output, retcode = _exec_command_tty(args)
        if retcode and not ignore_errors:
            _raise_command_error(args, retcode, stdout=output)
        return {
            'stdout': output,
            'stderr': '',
            'output': output,
            'retcode': retcode,
        }

    p = subprocess.Popen(
        args,
        stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if combine_stderr else subprocess.PIPE,
    )
    stdout, stderr = p.communicate(input=stdin_data)
    retcode = p.returncode

    stdout_decoded = stdout.decode('utf-8', errors='replace')
    stderr_decoded = '' if combine_stderr else stderr.decode('utf-8', errors='replace')

    if retcode and not ignore_errors:
        _raise_command_error(args, retcode, stdout=stdout_decoded, stderr=stderr_decoded)

    return {
        'stdout': stdout_decoded,
        'stderr': stderr_decoded,
        'output': stdout_decoded,
        'retcode': retcode,
    }


def _exec_nofetch(args):
    _exec_command(args)


def _exec_fetch(args, ignore_errors=False):
    return _exec_command(args, ignore_errors=ignore_errors)['stdout']


def _exec_fetch_tty(args, ignore_errors=False):
    result = _exec_command(args, ignore_errors=ignore_errors, use_tty=True)
    return result['output'], result['retcode']


def omd_bool_encode(value):
    '''
    Encode defined omd config strings from boolean python values
    '''

    if isinstance(value, bool):
        if value :
            return "on"
        else:
            return "off"
    elif isinstance(value, str):
        return value
    elif isinstance(value, int):
        return str(value)
    else:
        raise salt.exceptions.CommandExecutionError("Unspecified value type. Value: {} must be a string or integer".format(value))

def omd_bool_decode(value):
    '''
    Decode defined omd strings to boolean python values
    '''

    if isinstance(value, str):
        if value.lower() == "on":
            return True
        elif value.lower() == "off":
            return False
        else:
            return value
    else:
        raise salt.exceptions.CommandExecutionError("Unsupported value type. Value: {} must be a string".format(value))


def _check_site_exists(name):
    if not site_exists(name):
        raise salt.exceptions.CommandExecutionError("Site [{}] does not exist.".format(name))

def sites():
    
    '''
    Show list of configured OMD sites
    '''
    # Show a list of all sites and the version of OMD each site uses.
    # Option  -b or --bare, prints output without a headline
    return _exec_fetch(['/usr/bin/omd', 'sites', '--bare']).splitlines()

def site_exists(name):
    
    '''
    Check OMD site still exists
    '''
    return name in sites()

def site_config_value_exists(name, key):
    '''
    Check OMD config value already exists
    '''
    return key in config_show(name)


def site_version(name):
    '''
    Return the version of the specified OMD site
    '''

    _check_site_exists(name)
    output = _exec_fetch(['/usr/bin/omd', 'version', name])
    return output.split()[-1]

def def_version():
    '''
    Return the currently set default version of OMD
    '''

    output = _exec_fetch(['/usr/bin/omd', 'version'])
    return output.split()[-1]

def versions():
    '''
    Return installed OMD versions
    '''

    versions = []
    output = _exec_fetch(['/usr/bin/omd', 'versions'])
    # 1.5.0p16.cre 
    # 1.6.0p8.cre (default)
    for line in output.splitlines():
        # honor only the first column
        versions.append(line.split()[0])
    return versions

def update_site(name, version=None, conflict='install', logfile=None, preserve_colors=True):
    '''
    Update SITE to the current default version of OMD or to the defined explicit defined VERSION

    Args:
        name: Name of the OMD site
        version: Target version (optional, defaults to current default version)
        conflict: Conflict resolution strategy (default: 'install')
        logfile: Path to logfile for update output (optional, defaults to /omd/sites/<sitename>/var/log/omd_update.log)
        preserve_colors: Preserve ANSI colors in logged command output (default: True)
    '''

    # if site not exits, abort update
    _check_site_exists(name)
    args = ['/usr/bin/omd', '--force']

    if version:
        target_version = version
        args.extend(['-V', version])
    else:
        #default version
        target_version = def_version()

    current_version = site_version(name)
    if current_version == target_version:
        return 'Site {} already at the defined version {}'.format(name,target_version)

    was_running = site_running(name)

    args.extend(['update', '--conflict', conflict])
    args.append(name)

    LOGGER.debug(
        'Starting OMD update for site=%s target_version=%s preserve_colors=%s command=%s',
        name,
        target_version,
        preserve_colors,
        ' '.join(args),
    )

    # Write output to logfile
    if logfile is None:
        logfile = f'/omd/sites/{name}/var/log/omd_update_{datetime.now().strftime("%Y%m%d-%H%M%S")}.log'

    if was_running:
        site_stop(name)

    try:
        result = _exec_command(args, ignore_errors=True, use_tty=preserve_colors)
        output_decoded = result['output']
        retcode = result['retcode']
        details = _strip_ansi(output_decoded).strip() or 'No command output captured.'
        logged_output = output_decoded if preserve_colors else _strip_ansi(output_decoded)

        # Ensure log directory exists
        log_dir = os.path.dirname(logfile)
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, mode=0o755)
            except OSError as e:
                LOGGER.warning('Could not create update log directory %s for site=%s: %s', log_dir, name, e)

        try:
            with open(logfile, 'a') as f:
                f.write(_build_update_log_entry(name, target_version, args, retcode, details, logged_output, preserve_colors))
            LOGGER.info(
                'OMD update output logged for site=%s target_version=%s retcode=%s logfile=%s',
                name,
                target_version,
                retcode,
                logfile,
            )
        except IOError as e:
            LOGGER.warning('Could not write update log for site=%s logfile=%s: %s', name, logfile, e)

        if retcode:
            raise salt.exceptions.CommandExecutionError(
                "Command '{cmd}' returned: {ret}. Details: {details}. Logfile: {logfile}".format(
                    cmd=" ".join(args),
                    ret=retcode,
                    details=details,
                    logfile=logfile,
                )
            )

        return _strip_ansi(output_decoded)
    finally:
        if was_running:
            site_start(name)

def create_site(name, version=None, admin_password=None, no_tmpfs=None, tmpfs_size=None):
    '''
    Create a new site. The name of the site must be at most 16 characters long and consist only of letters, digits and underscores. It cannnot begin with a digit.
    '''

    if site_exists(name):
        raise salt.exceptions.CommandExecutionError("Site [{}] already exists".format(name))

    args = ['/usr/bin/omd']
    
    if version:
        args.extend(['-V', version])

    args.append('create')

    if admin_password:
        args.extend(['--admin-password', admin_password])
    if no_tmpfs:
        args.append('--no-tmpfs')
    else:
        if tmpfs_size:
            args.extend(['-t', tmpfs_size])

    args.append(name)
    LOGGER.debug(args)
    return _exec_fetch(args)

def remove_site(name):
    '''
    Remove existing OMD site (and its data)
    '''

    if not site_exists(name):
        raise salt.exceptions.CommandExecutionError("Site [{}] does not exist.".format(name))

    args = ['/usr/bin/omd', 'rm', name]
    _exec_command(args, stdin_data=b'yes\n', combine_stderr=True)
    return "Site [{}] successfully removed".format(name)

def site_status(name):
    
    '''
    Return component and overall status of the specified omd site
    '''

    _check_site_exists(name)
    ret = {}
    output = _exec_fetch(['/usr/bin/omd', 'status', '--bare', name], ignore_errors=True)
    for line in output.splitlines():
        key, value = line.split()
        ret[key] = int(value)
    return ret

def site_stopped(name):
    _check_site_exists(name)
    return site_status(name)['OVERALL'] == 1

def site_running(name):
    _check_site_exists(name)
    return site_status(name)['OVERALL'] == 0

def site_start(name):
    '''
    Start OMD site
    '''

    _exec_nofetch(['/usr/bin/omd', 'start', name])

def site_stop(name):
    '''
    Stop OMD site
    '''
    
    _exec_nofetch(['/usr/bin/omd', 'stop', name])
    return 'Site {} successfully stopped'.format(name)

def config_show(name):
    '''
    omd.config_show [SITE]
    Return the current settings of all variables of the specified SITE
    '''

    _check_site_exists(name)
    ret = {}
    output = _exec_fetch(['/usr/bin/omd', 'config', name, 'show'])
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if ': ' not in line:
            LOGGER.warning("Ignoring unexpected output line from 'omd config %s show': %r", name, line)
            continue
        k, v = line.split(': ', 1)
        ret[k] = omd_bool_decode(v.strip())
    return ret

def config_show_value(name, key):
    '''
    omd.config_show [SITE] [VALUE]
    Return specific configuration value of an OMD Site
    '''
    args = ['/usr/bin/omd', 'config', name, 'show', key]
    _check_site_exists(name)
    _check_site_config_value_exists(name, key)

    ret = omd_bool_decode(_exec_fetch(args).strip())
    return ret

def site_is_config_value(name, key, value):
    '''
    Check configuration value of OMD site
    '''
    # Compare given config value with site config value
    return omd_bool_encode(config_show_value(name, key)) == omd_bool_encode(value)

def site_set_config_value(name, key, value):
    '''
    Set configuration value of OMD site
    '''
    args = ['/usr/bin/omd', 'config', name, 'set', key, omd_bool_encode(value)]
    _check_site_exists(name)
    _check_site_config_value_exists(name, key)
    if not site_stopped(name):
        raise salt.exceptions.CommandExecutionError("Site [{}] is currently running. Stop site before setting config values".format(name))

    ret = _exec_fetch(args)
    return ret


