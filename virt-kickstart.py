#!/usr/bin/env python3

# TODO:
# * if you do a cloud-init install and the user-data file should power-off the VM
# * if the cloud-init user-data does a power-off, then the vm will be down and should
#   be started
# * a config file would be nice for the DEFAULT_* settings
# * relative file references should be resolved relative to a datadir
# * add a debug/verbose option to dump some state and print various progress steps 

import getopt, sys
import tempfile
import os
import getpass
from passlib.hash import sha512_crypt
import random
import re

from jinja2 import Environment, BaseLoader, TemplateNotFound
from os.path import join, exists, getmtime

# the FileSystemLoader wants templates to be relative to some searchpath
# this is probably a good idea, but for now I'd rather let the user just
# pass in a file name and load it directly
class MyLoader(BaseLoader):

    def get_source(self, environment, template):
        if not exists(template):
            raise TemplateNotFound(template)
        mtime = getmtime(template)
        with open(template) as f:
            source = f.read()
        return source, template, lambda: mtime == getmtime(template)


FLAVORS = {
  'alma8': {
      'os_variant': 'almalinux8',
      'location': 'https://mirrors.ocf.berkeley.edu/almalinux/8/BaseOS/x86_64/os/',
      'kickstart': 'kickstart/alma.tmpl',
  },
  'alma9': {
      'os_variant': 'almalinux9',
      'location': 'https://mirrors.ocf.berkeley.edu/almalinux/9/BaseOS/x86_64/os/',
      'kickstart': 'kickstart/alma.tmpl',
  },
  'fedora39': {
      'os_variant': 'fedora39',
      'location': 'https://mirror.math.princeton.edu/pub/fedora/linux/releases/39/Everything/x86_64/os/',
      'kickstart': 'kickstart/fedora.tmpl',
  },
  'ubuntu20.04': {
      'os_variant': 'ubuntu20.04',
      'location': 'https://mirrors.bloomu.edu/ubuntu/dists/focal/main/installer-amd64/',
      'kickstart': 'kickstart/ubuntu.tmpl',
  }
}

DEFAULT_FLAVOR = 'alma8'
DEFAULT_MEMORY = "4096"
DEFAULT_VCPUS = "1"
DEFAULT_DISK_SIZE = "20"
DEFAULT_BRIDGE = "virbr0"
DEFAULT_KERNEL_ARGS = "console=ttyS0"

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def usage():
    eprint("virt-kickstart.py [options]")
    eprint("  -b BRIDGE    use BRIDGE")
    eprint("  -C           use cloud-init")
    eprint("  -c VALUE     virtual cpus")
    eprint("  -d VALUE     disk size in MB")
    eprint("  -F FLAVOR    use defaults for FLAVOR (default: %s)" % DEFAULT_FLAVOR)
    eprint("  -h           show usage information")
    eprint("  -i IP        use IP for static dhcp map")
    eprint("  -I FILE      use disk image")
    eprint("  -k FILE      kickstart file")
    eprint("  -l LOCATION  get instalation files from LOCATION")
    eprint("  -m VALUE     vm memory in MB")
    eprint("  -n           no reboot after install")
    eprint("  -o OS        use OS as os_variant (default: %s" % FLAVORS[DEFAULT_FLAVOR]['os_variant'])
    eprint("  -x ARGS      add extra args to kernel command line")

def random_mac():
    return "52:54:00:%02x:%02x:%02x" % (random.randint(0, 255),
                                        random.randint(0, 255),
                                        random.randint(0, 255))

def render_tmpl(tmpl_file, output_file, context):
    environment = Environment(loader=MyLoader())
    template = environment.get_template(tmpl_file)

    content = template.render(context)

    with open(output_file, mode="w", encoding="utf-8") as output:
        output.write(content)
        eprint("wrote template: %s" % output_file)

def main():

    try:
        opts, args = getopt.getopt(
                sys.argv[1:],
                "b:Cc:d:F:hI:i:k:l:M:m:no:U:x:",
                ["bridge=", "cloud-init", "cpus", "disk-size", "flavor=", "help", "image=", "ipaddr=", "kickstart=", "location=", "meta-data=", "memory=", "os-variant=", "noreboot", "user-data", "extra-args"]
            )
    except getopt.GetoptError as err:
        eprint(err)
        usage()
        sys.exit(2)

    use_location = True
    use_cloud_init = False

    flavor = DEFAULT_FLAVOR
    ks_template = None
    bridge = DEFAULT_BRIDGE
    vcpus = DEFAULT_VCPUS
    disk_size = DEFAULT_DISK_SIZE
    location = None
    memory = DEFAULT_MEMORY
    image_file = None
    noreboot = False
    meta_data = None
    user_data = None
    ipaddr = None
    os_variant = None
    extra_kernel_args = None

    for o, a in opts:
        if o in ("-b", "--bridge"):
            bridge = a
        elif o in ("-C", "--cloud-init"):
            use_cloud_init = True
        elif o in ("-c", "--cpus"):
            vcpus = a
        elif o in ("-d", "--disk-size"):
            disk_size = a
        elif o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-I", "--image-file"):
            image_file = a
            # FIXME - check that image_file exists
        elif o in ("-i", "--ipaddr"):
            ipaddr = a
            # FIXME - check that ipaddr is correctly formatted
        elif o in ("-k", "--kickstart"):
            ks_template = a
            # FIXME - check that ks_template exists
        elif o in ("-l", "--location"):
            location = a
        elif o in ("-M", "--meta-data"):
            meta_data = a
            # FIXME - check that meta_data file exists
        elif o in ("-m", "--memory"):
            memory = a
        elif o in ("-n", "--noreboot"):
            noreboot = True
        elif o in ("-o", "--os-variant"):
            os_variant = a
        elif o in ("-U", "--user-data"):
            user_data = a
            # FIXME - check that user_data file exists
        elif o in ("-F", "--flavor"):
            flavor = a
        elif o in ("-x", "--extra-args"):
            extra_kernel_args = a
        else:
            assert False, "unhandled option"

    # we now need to untangle any weirdness with the setting of
    # flavor and the settings that are tangled up with it:
    # ks_template, locationg, os_variant
    if ks_template is None:
        ks_template = FLAVORS[flavor]['kickstart']

    if location is None:
        location = FLAVORS[flavor]['location']

    if os_variant is None:
        os_variant = FLAVORS[flavor]['os_variant']

    if extra_kernel_args is None:
        extra_kernel_args = DEFAULT_KERNEL_ARGS
    else:
        extra_kernel_args = "%s %s" % (DEFAULT_KERNEL_ARGS, extra_kernel_args)

    # args should be a list contain a single time: the vm name
    if (len(args) != 1):
        usage()
        sys.exit(2)

    hostname = args[0]

    #print("hostname: '%s'" % hostname)
    #print("ipaddr: '%s'" % ipaddr)
    #print("bridge: '%s'" % bridge)
    #print("use_cloud_init: '%s'" % use_cloud_init)
    #print("vcpus: '%s'" % vcpus)
    #print("disk_size: '%s'" % disk_size)
    #print("image_file: '%s'" % image_file)
    #print("kickstart_file: '%s'" % kickstart_file)
    #print("location: '%s'" % location)
    #print("memory: '%s'" % memory)
    #print("noreboot: '%s'" % noreboot)
    #print("meta_data: '%s'" % meta_data)
    #print("user_data: '%s'" % user_data)

    mac = random_mac()

    if ipaddr:
        # make a static mapping
        net_update_options = [
            'virsh',
            'net-update',
            'default',
            'add',
            'ip-dhcp-host',
            f'''"<host mac='{mac}' name='{hostname}' ip='{ipaddr}' />"''',
            '--live',
            '--config',
        ]
        net_update_cmd = ' '.join(net_update_options)
        eprint(net_update_cmd)
        res = os.system(net_update_cmd)
        if (res >> 8 != 0):
            eprint("ERROR: setting static dhcp entry (%d)" % (res >> 8))
            sys.exit(1)

        net_update_options = [
            'virsh',
            'net-update',
            'default',
            'add',
            'dns-host',
            f'''"<host ip='{ipaddr}'><hostname>{hostname}</hostname></host>"''',
            '--live',
            '--config',
        ]
        net_update_cmd = ' '.join(net_update_options)
        eprint(net_update_cmd)
        res = os.system(net_update_cmd)
        if (res >> 8 != 0):
            eprint("ERROR: setting static dns-host entry (%d)" % (res >> 8))
            sys.exit(1)

    # USE_CLOUD_INIT requires META_DATA and USER_DATA
    if use_cloud_init:
        if not meta_data:
            eprint("error: cloud-init requires meta_data")
            sys.exit(1)

        if not user_data:
            eprint("error: cloud-init requires user_data")
            sys.exit(1)

        # create cloud-init disk image
        (ci_filehandle, ci_filename) = tempfile.mkstemp(prefix="%s." % hostname, suffix=".cidata")
        os.close(ci_filehandle)

        # FIXME - check return values
        res = os.system("truncate -s 1M %s" % ci_filename)
        res = os.system("mkfs.vfat %s" % ci_filename)
        res = os.system("mlabel -i %s ::cidata" % ci_filename)
        res = os.system("mcopy -i %s %s ::meta-data" % (ci_filename, meta_data))
        res = os.system("mcopy -i %s %s ::user-data" % (ci_filename, user_data))

        cidata_disk_value = "path=%s,bus=virtio" % ci_filename

        # USE_CLOUD_INIT implies that NOREBOOT is unset
        noreboot = False

    if image_file:
        primary_disk = "size=%s,bus=virtio,backing_store=%s" % (disk_size, disk_image)

        eprint("warning: disk_size is currently ignored for image-based builds")

        # FIXME - warn if using location
        use_location = False
    else:
        (ks_filehandle, ks_filename) = tempfile.mkstemp(prefix="%s." % hostname, suffix=".ks")

        eprint("Please set a root password for %s: " % hostname)
        rootpw = getpass.getpass()
        if rootpw == getpass.getpass('Confirm: '):
            rootpw_hash = sha512_crypt.hash(rootpw)
        else:
            eprint("error: passwords don't match")
            sys.exit(1)

        # for ubuntu, the @LOCATION@ should be the 'base' of the ubuntu tree.
        # ex. https://mirror.com/ubuntu
        #
        match = re.search(r'ubuntu', os_variant)
        if match:
            match = re.search(r'(^.*/)dists/', location)
            if match:
                tmpl_location = match.group(1)
            else:
                eprint("ERROR: location URL doesn't look right") # FIXME: ???
                sys.exit(1)
        else:
            tmpl_location = location

        context = {
                'hostname': hostname,
                'rootpw_hash': rootpw_hash,
                'location': tmpl_location
        }
        render_tmpl(ks_template, ks_filename, context)

        primary_disk = "size=%s,bus=virtio" % disk_size
        initrd_inject = ks_filename

        # we have to change the inst.xxx to just xxx for ubuntu
        if re.match(r'ubuntu', os_variant):
            inst_repo = "repo=%s" % location
            inst_ks = "ks=file:/%s" % os.path.basename(ks_filename)
        else:
            inst_repo = "inst.repo=%s" % location
            inst_ks = "inst.ks=file:/%s" % os.path.basename(ks_filename)

        extra_kernel_args = "'%s %s %s'" % (extra_kernel_args, inst_ks, inst_repo)
    
    virt_install_options = ['virt-install']

    virt_install_options.append('--os-variant')
    virt_install_options.append(os_variant)

    virt_install_options.append('--name')
    virt_install_options.append(hostname)

    virt_install_options.append('--memory')
    virt_install_options.append(memory)

    virt_install_options.append('--vcpus')
    virt_install_options.append(vcpus)

    virt_install_options.append('--network')
    virt_install_options.append("model=virtio,bridge=%s,mac=%s" % (bridge, mac))

    virt_install_options.append('--disk')
    virt_install_options.append(primary_disk)

    virt_install_options.append('--graphics')
    virt_install_options.append('none')

    if use_location:
        virt_install_options.append('--location')
        virt_install_options.append(location)

    if use_cloud_init:
        virt_install_options.append('--disk')
        virt_install_options.append(cidata_disk_value)

    if 'initrd_inject' in locals():
        virt_install_options.append('--initrd-inject')
        virt_install_options.append(initrd_inject)

    if 'extra_kernel_args' in locals():
        virt_install_options.append('--extra-args')
        virt_install_options.append(extra_kernel_args)

    virt_install_cmd = ' '.join(virt_install_options)
    #print(virt_install_cmd)

    res = os.system(virt_install_cmd)

    # if we're doing a location build (ie. a real build) then we have to ... what?

    if 'ks_filename' in locals():
        os.remove(ks_filename)

    if use_cloud_init:
        res = os.system(f"virsh detach-disk {hostname} {ci_filename} --persistent")
        if (res >> 8 != 0):
            eprint("ERROR: removing cidata device (%d)" % (res >> 8))
            sys.exit(1)

        # if using cloud-init, the default user-data does a poweroff so we have to restart the vm
        res = os.system(f"virsh start {hostname}")
        if (res >> 8 != 0):
            eprint("ERROR: removing cidata device (%d)" % (res >> 8))
            sys.exit(1)


if __name__ == "__main__":
    main()
