# (c) 2012-2013 Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import OrderedDict
import json
from logging import getLogger
import os
from os import listdir
from os.path import exists, expanduser, isfile, join
import re
import sys

from .conda_argparse import add_parser_json, add_parser_offline
from ..common.compat import iteritems, itervalues, on_win

log = getLogger(__name__)

help = "Display information about current conda install."

example = """

Examples:

    conda info -a
"""

def configure_parser(sub_parsers):
    p = sub_parsers.add_parser(
        'info',
        description=help,
        help=help,
        epilog=example,
    )
    add_parser_json(p)
    add_parser_offline(p)
    p.add_argument(
        '-a', "--all",
        action="store_true",
        help="Show all information, (environments, license, and system "
             "information.")
    p.add_argument(
        '-e', "--envs",
        action="store_true",
        help="List all known conda environments.",
    )
    p.add_argument(
        '-l', "--license",
        action="store_true",
        help="Display information about the local conda licenses list.",
    )
    p.add_argument(
        '-s', "--system",
        action="store_true",
        help="List environment variables.",
    )
    p.add_argument(
        'packages',
        action="store",
        nargs='*',
        help="Display information about packages.",
    )
    p.add_argument(
        '--root',
        action='store_true',
        help='Display root environment path.',
    )
    p.add_argument(
        '--unsafe-channels',
        action='store_true',
        help='Display list of channels with tokens exposed.',
    )
    p.set_defaults(func=execute)


def get_user_site():  # pragma: no cover
    site_dirs = []
    try:
        if not on_win:
            if exists(expanduser('~/.local/lib')):
                python_re = re.compile('python\d\.\d')
                for path in listdir(expanduser('~/.local/lib/')):
                    if python_re.match(path):
                        site_dirs.append("~/.local/lib/%s" % path)
        else:
            if 'APPDATA' not in os.environ:
                return site_dirs
            APPDATA = os.environ[str('APPDATA')]
            if exists(join(APPDATA, 'Python')):
                site_dirs = [join(APPDATA, 'Python', i) for i in
                             listdir(join(APPDATA, 'PYTHON'))]
    except (IOError, OSError) as e:
        log.debug('Error accessing user site directory.\n%r', e)
    return site_dirs


IGNORE_FIELDS = {'files', 'auth', 'preferred_env', 'priority'}

SKIP_FIELDS = IGNORE_FIELDS | {'name', 'version', 'build', 'build_number',
                               'channel', 'schannel', 'size', 'fn', 'depends'}


def dump_record(pkg):
    return {k: v for k, v in iteritems(pkg.dump()) if k not in IGNORE_FIELDS}


def pretty_package(dist, pkg):
    from ..utils import human_bytes

    pkg = dump_record(pkg)
    d = OrderedDict([
        ('file name', dist.to_filename()),
        ('name', pkg['name']),
        ('version', pkg['version']),
        ('build string', pkg['build']),
        ('build number', pkg['build_number']),
        ('channel', dist.channel),
        ('size', human_bytes(pkg['size'])),
    ])
    for key in sorted(set(pkg.keys()) - SKIP_FIELDS):
        d[key] = pkg[key]

    print()
    header = "%s %s %s" % (d['name'], d['version'], d['build string'])
    print(header)
    print('-'*len(header))
    for key in d:
        print("%-12s: %s" % (key, d[key]))
    print('dependencies:')
    for dep in pkg['depends']:
        print('    %s' % dep)


def print_package_info(packages):
    from .common import arg2spec, stdout_json
    from ..core.index import get_index
    from ..base.context import context
    from ..resolve import Resolve
    index = get_index()
    r = Resolve(index)
    if context.json:
        stdout_json({
            package: [dump_record(r.index[d])
                      for d in r.get_dists_for_spec(arg2spec(package))]
            for package in packages
        })
    else:
        for package in packages:
            for dist in r.get_dists_for_spec(arg2spec(package)):
                pretty_package(dist, r.index[dist])


def get_info_dict(system=False):
    from .. import CONDA_PACKAGE_ROOT, __version__ as conda_version
    from ..base.context import conda_in_private_env, context, sys_rc_path, user_rc_path
    from ..common.url import mask_anaconda_token
    from ..models.channel import offline_keep, prioritize_channels

    try:
        from ..install import linked_data
        root_pkgs = linked_data(context.root_prefix)
    except:  # pragma: no cover
        root_pkgs = {}

    try:
        from requests import __version__ as requests_version
        # These environment variables can influence requests' behavior, along with configuration
        # in a .netrc file
        #   REQUESTS_CA_BUNDLE
        #   HTTP_PROXY
        #   HTTPS_PROXY
    except ImportError:  # pragma: no cover
        try:
            from pip._vendor.requests import __version__ as requests_version
        except Exception as e:  # pragma: no cover
            requests_version = "Error %r" % e
    except Exception as e:  # pragma: no cover
        requests_version = "Error %r" % e

    try:
        from conda_env import __version__ as conda_env_version
    except:  # pragma: no cover
        try:
            cenv = [p for p in itervalues(root_pkgs) if p['name'] == 'conda-env']
            conda_env_version = cenv[0]['version']
        except:
            conda_env_version = "not installed"

    try:
        import conda_build
    except ImportError:  # pragma: no cover
        conda_build_version = "not installed"
    except Exception as e:  # pragma: no cover
        conda_build_version = "Error %s" % e
    else:  # pragma: no cover
        conda_build_version = conda_build.__version__

    channels = list(prioritize_channels(context.channels).keys())
    if not context.json:
        channels = [c + ('' if offline_keep(c) else '  (offline)')
                    for c in channels]
    channels = [mask_anaconda_token(c) for c in channels]

    config_files = tuple(path for path in context.collect_all()
                         if path not in ('envvars', 'cmd_line'))

    netrc_file = os.environ.get('NETRC')
    if not netrc_file:
        user_netrc = expanduser("~/.netrc")
        if isfile(user_netrc):
            netrc_file = user_netrc

    from ..core.envs_manager import EnvsDirectory
    active_prefix_name = EnvsDirectory.env_name(context.active_prefix)

    info_dict = dict(
        platform=context.subdir,
        conda_version=conda_version,
        conda_env_version=conda_env_version,
        conda_build_version=conda_build_version,
        root_prefix=context.root_prefix,
        conda_prefix=context.conda_prefix,
        conda_private=conda_in_private_env(),
        root_writable=context.root_writable,
        pkgs_dirs=context.pkgs_dirs,
        envs_dirs=context.envs_dirs,
        default_prefix=context.default_prefix,
        active_prefix=context.active_prefix,
        active_prefix_name=active_prefix_name,
        conda_shlvl=context.shlvl,
        channels=channels,
        user_rc_path=user_rc_path,
        rc_path=user_rc_path,
        sys_rc_path=sys_rc_path,
        # is_foreign=bool(foreign),
        offline=context.offline,
        envs=[],
        python_version='.'.join(map(str, sys.version_info)),
        requests_version=requests_version,
        user_agent=context.user_agent,
        conda_location=CONDA_PACKAGE_ROOT,
        config_files=config_files,
        netrc_file=netrc_file,
    )
    if on_win:
        from ..common.platform import is_admin_on_windows
        info_dict['is_windows_admin'] = is_admin_on_windows()
    else:
        info_dict['UID'] = os.geteuid()
        info_dict['GID'] = os.getegid()

    if system:
        evars = ['PATH', 'PYTHONPATH', 'PYTHONHOME', 'CONDA_DEFAULT_ENV', 'CONDA_ENVS_PATH']

        if context.platform == 'linux':
            evars.append('LD_LIBRARY_PATH')
        elif context.platform == 'osx':
            evars.append('DYLD_LIBRARY_PATH')

        info_dict.update({
            'sys.version': sys.version,
            'sys.prefix': sys.prefix,
            'sys.executable': sys.executable,
            'site_dirs': get_user_site(),
            'env_vars': {ev: os.getenv(ev, '<not set>') for ev in evars},
        })

    return info_dict


def get_main_info_str(info_dict):
    for key in 'pkgs_dirs', 'envs_dirs', 'channels', 'config_files':
        info_dict['_' + key] = ('\n' + 26 * ' ').join(info_dict[key])
    info_dict['_rtwro'] = ('writable' if info_dict['root_writable'] else 'read only')

    format_param = lambda nm, val: "%23s : %s" % (nm, val)

    builder = ['']

    if info_dict['active_prefix_name']:
        builder.append(format_param('active environment', info_dict['active_prefix_name']))
        builder.append(format_param('active env location', info_dict['active_prefix']))
    else:
        builder.append(format_param('active environment', info_dict['active_prefix']))

    if info_dict['conda_shlvl'] >= 0:
        builder.append(format_param('shell level', info_dict['conda_shlvl']))

    builder.extend((
        format_param('user config file', info_dict['user_rc_path']),
        format_param('populated config files', info_dict['_config_files']),
        format_param('conda version', info_dict['conda_version']),
        format_param('conda-build version', info_dict['conda_build_version']),
        format_param('python version', info_dict['python_version']),
        format_param('base environment', '%s  (%s)' % (info_dict['root_prefix'],
                                                       info_dict['_rtwro'])),
        format_param('channel URLs', info_dict['_channels']),
        format_param('package cache', info_dict['_pkgs_dirs']),
        format_param('envs directories', info_dict['_envs_dirs']),
        format_param('platform', info_dict['platform']),
        format_param('user-agent', info_dict['user_agent']),
    ))

    if on_win:
        builder.append(format_param("administrator", info_dict['is_windows_admin']))
    else:
        builder.append(format_param("UID:GID", '%s:%s' % (info_dict['UID'], info_dict['GID'])))

    builder.extend((
        format_param('netrc file', info_dict['netrc_file']),
        format_param('offline mode', info_dict['offline']),
    ))

    builder.append('')
    return '\n'.join(builder)


def execute(args, parser):
    from .common import handle_envs_list, stdout_json
    from ..base.context import context

    if args.root:
        if context.json:
            stdout_json({'root_prefix': context.root_prefix})
        else:
            print(context.root_prefix)
        return

    if args.packages:
        from ..resolve import ResolvePackageNotFound
        try:
            print_package_info(args.packages)
            return
        except ResolvePackageNotFound as e:  # pragma: no cover
            from ..exceptions import PackagesNotFoundError
            raise PackagesNotFoundError(e.bad_deps)

    if args.unsafe_channels:
        if not context.json:
            print("\n".join(context.channels))
        else:
            print(json.dumps({"channels": context.channels}))
        return 0

    options = 'envs', 'system', 'license'

    if args.all or context.json:
        for option in options:
            setattr(args, option, True)
    info_dict = get_info_dict(args.system)

    if (args.all or all(not getattr(args, opt) for opt in options)) and not context.json:
        print(get_main_info_str(info_dict))

    if args.envs:
        handle_envs_list(info_dict['envs'], not context.json)

    if args.system:
        if not context.json:
            from .find_commands import find_commands, find_executable
            print("sys.version: %s..." % (sys.version[:40]))
            print("sys.prefix: %s" % sys.prefix)
            print("sys.executable: %s" % sys.executable)
            print("conda location: %s" % info_dict['conda_location'])
            for cmd in sorted(set(find_commands() + ('build',))):
                print("conda-%s: %s" % (cmd, find_executable('conda-' + cmd)))
            print("user site dirs: ", end='')
            site_dirs = info_dict['site_dirs']
            if site_dirs:
                print(site_dirs[0])
            else:
                print()
            for site_dir in site_dirs[1:]:
                print('                %s' % site_dir)
            print()

            for name, value in sorted(iteritems(info_dict['env_vars'])):
                print("%s: %s" % (name, value))
            print()

    if args.license and not context.json:
        try:
            from _license import show_info
            show_info()  # pragma: no cover
        except ImportError:
            print("""\
WARNING: could not import _license.show_info
# try:
# $ conda install -n root _license""")
        except Exception as e:  # pragma: no cover
            log.warn('%r', e)

    if context.json:
        stdout_json(info_dict)
