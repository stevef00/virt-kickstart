#!/usr/bin/env python3

# TODO:
# * if you do a cloud-init install and the user-data file should power-off the VM
# * if the cloud-init user-data does a power-off, then the vm will be down and should
#   be started
# * a config file would be nice for the DEFAULT_* settings

import getopt, sys
import tempfile
import os
import crypt, getpass

DEFAULT_LOCATION = "https://mirror.umd.edu/centos/8/BaseOS/x86_64/os/"

DEFAULT_MEMORY = "4096"
DEFAULT_VCPUS = "1"
DEFAULT_DISK_SIZE = "20"
DEFAULT_KS_TMPL = "c8.tmpl"
DEFAULT_BRIDGE = "virbr0"
DEFAULT_KS_TEMPLATE = "c8.tmpl"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def usage():
    eprint("virt-kickstart.py [options]")
    eprint("  -b BRIDGE    use BRIDGE")
    eprint("  -C           use cloud-init")
    eprint("  -c VALUE     virtual cpus")
    eprint("  -d VALUE     disk size in MB")
    eprint("  -h           show usage information")
    eprint("  -I FILE      use disk image")
    eprint("  -k FILE      kickstart file")
    eprint("  -l LOCATION  get instalation files from LOCATION")
    eprint("  -m VALUE     vm memory in MB")
    eprint("  -n           no reboot after install")

def main():

    try:
        opts, args = getopt.getopt(
                sys.argv[1:],
                "b:Cc:d:hI:k:l:M:m:nU:",
                ["bridge=", "cloud-init", "cpus", "disk-size", "help", "image=", "kickstart=", "location=", "meta-data=", "memory=", "noreboot", "user-data"]
            )
    except getopt.GetoptError as err:
        eprint(err)
        usage()
        sys.exit(2)

    use_location = True
    use_cloud_init = False

    ks_template = DEFAULT_KS_TEMPLATE
    bridge = DEFAULT_BRIDGE
    vcpus = DEFAULT_VCPUS
    disk_size = DEFAULT_DISK_SIZE
    location = DEFAULT_LOCATION
    memory = DEFAULT_MEMORY
    image_file = None
    kickstart_file = None
    noreboot = False
    meta_data = None
    user_data = None

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
        elif o in ("-k", "--kickstart"):
            kickstart_file = a
            # FIXME - check that kickstart_file exists
        elif o in ("-l", "--location"):
            location = a
        elif o in ("-M", "--meta-data"):
            meta_data = a
            # FIXME - check that meta_data file exists
        elif o in ("-m", "--memory"):
            memory = a
        elif o in ("-n", "--noreboot"):
            noreboot = True
        elif o in ("-U", "--user-data"):
            user_data = a
            # FIXME - check that user_data file exists
        else:
            assert False, "unhandled option"


    # args should be a list contain a single time: the vm name
    if (len(args) != 1):
        usage()
        sys.exit(2)

    hostname = args[0]

    #print("hostname: '%s'" % hostname)
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
            rootpw_hash = crypt.crypt(rootpw)
        else:
            eprint("error: passwords don't match")
            sys.exit(1)

        # do tmpl param replacement
        res = os.system("sed -e 's|@HOSTNAME@|%s|g' -e 's|@ROOTPW_HASH@|%s|g' %s > %s" % (hostname, rootpw_hash, ks_template, ks_filename))

        primary_disk = "size=%s,bus=virtio" % disk_size
        initrd_inject = ks_filename
        extra_args = "'console=ttyS0 ks=file:/%s'" % os.path.basename(ks_filename)

    
    virt_install_options = ['virt-install']

    virt_install_options.append('--name')
    virt_install_options.append(hostname)

    virt_install_options.append('--memory')
    virt_install_options.append(memory)

    virt_install_options.append('--vcpus')
    virt_install_options.append(vcpus)

    virt_install_options.append('--network')
    virt_install_options.append("model=virtio,bridge=%s" % bridge)

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

    if 'extra_args' in locals():
        virt_install_options.append('--extra-args')
        virt_install_options.append(extra_args)

    virt_install_cmd = ' '.join(virt_install_options)
    #print(virt_install_cmd)

    res = os.system(virt_install_cmd)

    # if we're doing a location build (ie. a real build) then we have to ... what?

    if 'ks_filename' in locals():
        os.remove(ks_filename)

    if use_cloud_init:
        res = os.system(f"virsh detach-disk {hostname} {ci_filename} --persistent")

if __name__ == "__main__":
    main()
