#!/usr/bin/env python3

import os
import time
import glanceclient.v2.client
import keystoneclient
import keystoneclient.v2_0.client
import novaclient.client

import paramiko


class SSHSession():
    def __init__(self, ip, cloud_user='root'):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        for i in range(60):
            try:
                client.connect(ip, port=22, username=cloud_user, allow_agent=True)
            except (OSError, ConnectionResetError):
                print('SSH: Waiting for %s' % ip)
                time.sleep(1)
            else:
                break
        self.client = client

    def __enter__(self):
        return self

    def run(self, cmd):
        transport = self.client.get_transport()
        ch = transport.open_session()
        ch.get_pty()
        ch.set_combine_stderr(True)
        ch.exec_command(cmd)
        buf = ''
        while True:
            new = ch.recv(1024).decode(encoding='UTF-8')
            print(new, end='', flush=True)
            buf += new
            if new == '' and ch.exit_status_ready():
                break
            time.sleep(0.1)
        retcode = ch.recv_exit_status()
        return (buf, retcode)

    def put(self, source, dest):
        transport = self.client.get_transport()
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(source, dest)

    def put_content(self, content, dest, mode='w'):
        transport = self.client.get_transport()
        sftp = paramiko.SFTPClient.from_transport(transport)
        file=sftp.file(dest, mode, -1)
        file.write(content)
        file.flush()

    def __exit__(self, exc_type, exc_value, traceback):
        self.client.close()

def get_id(nova, type_name, **kwargs):
    type_obj=getattr(nova, type_name + 's')
    for i in type_obj.list():
        found = True
        for k, v in kwargs.items():
            if not (hasattr(i, k) and (getattr(i, k) == v)):
                found = False
                break
        if found is True:
            return i.id

def get_floating_ip(nova):
    for floating_ip in nova.floating_ips.list():
        if floating_ip.instance_id is None:
            if floating_ip.fixed_ip is None:
                return floating_ip
    print("No more Floating IP")

# Authentication with Keystone
keystone = keystoneclient.v2_0.client.Client(
    auth_url=os.environ['OS_AUTH_URL'],
    username=os.environ['OS_USERNAME'],
    password=os.environ['OS_PASSWORD'],
    tenant_name=os.environ['OS_TENANT_NAME'])
nova = novaclient.client.Client(2,
    auth_url=os.environ['OS_AUTH_URL'],
    username=os.environ['OS_USERNAME'],
    api_key=os.environ['OS_PASSWORD'],
    project_id=os.environ['OS_TENANT_NAME'])
glance_endpoint = keystone.service_catalog.url_for(service_type='image')
print('a')
print(glance_endpoint)
glance = glanceclient.v2.client.Client(glance_endpoint, token=keystone.auth_token)


def bootstrap(nova):
# Start the Hypervisor
    server = nova.servers.create('bob',
                        get_id(nova, 'image', name='RHEL 7.2 x86_64'),
                        flavor=get_id(nova, 'flavor', name='m1.hypervisor'),
                        key_name='DCI',
                        nics=[{'net-id': get_id(nova, 'network', label='private')}])

    for i in range(0, 120):
        if server.status == 'ACTIVE':
            print("Server started in about %s seconds." % i)
            break
        if server.status == 'ERROR':
            print("nova boot has failed")
            print(server.diagnostics())
            break
        if i % 5 == 0:
            server = nova.servers.get(server.id)
            print(server.status)
        time.sleep(1)
    floating_ip = get_floating_ip(nova)
    server.add_floating_ip(floating_ip.ip)
    server.add_security_group('ssh')
    server.add_security_group('rhos-mirror-user')
    return server

servers = nova.servers.list(search_opts={'name': 'bob'})
if len(servers) > 0:
    server = servers[0]
else:
    server = bootstrap(nova)
ip = nova.servers.ips(server)['private'][1]['addr']

local_http_cache='192.168.1.2'
puddle_pin_version='2015-12-22.2'
puddle_director_pin_version='2015-12-03.1'
guest_image_path='/brewroot/packages/rhel-guest-image/7.2/20151102.0/images/rhel-guest-image-7.2-20151102.0.x86_64.qcow2'
guest_image_md5sum='486900b54f4757cb2d6b59d9bce9fe90'

content="[RH7-RHOS-8.0-director]\nname=RH7-RHOS-8.0\nbaseurl=http://%s/rel-eng/OpenStack/8.0-RHEL-7-director/%s/RH7-RHOS-8.0-director/x86_64/os/\ngpgcheck=0\nenabled=1\n" % (local_http_cache, puddle_pin_version)
dest='/etc/yum.repos.d/rhos-release-8-director.repo'
rhsm_login = 'gleboude@redhat.com'
rhsm_password = os.environ['RHN_PW']

with SSHSession(ip, 'cloud-user') as ssh:
    print(ssh.run("sudo sed -i 's,.*ssh-rsa,ssh-rsa,' /root/.ssh/authorized_keys"))

with SSHSession(ip) as ssh:
    if ssh.run('curl -o /tmp/nosync.rpm https://kojipkgs.fedoraproject.org//packages/nosync/1.0/1.el7/x86_64/nosync-1.0-1.el7.x86_64.rpm')[1] == 0:
        print(ssh.run('rpm -i /tmp/nosync.rpm'))
        print(ssh.run(' echo /usr/lib64/nosync/nosync.so > /etc/ld.so.preload'))
    else:
        print('Failed to fetch nosync rpm')
    content="[RH7-RHOS-8.0]\nname=RH7-RHOS-8.0\nbaseurl=http://%s/rel-eng/OpenStack/8.0-RHEL-7/%s/RH7-RHOS-8.0/x86_64/os/\ngpgcheck=0\nenabled=1" % (local_http_cache, puddle_pin_version)
    dest='/etc/yum.repos.d/rhos-release-8.repo'
    ssh.put_content(content, dest)

    content="[RH7-RHOS-8.0-director]\nname=RH7-RHOS-8.0\nbaseurl=http://%s/rel-eng/OpenStack/8.0-RHEL-7-director/%s/RH7-RHOS-8.0-director/x86_64/os/\ngpgcheck=0\nenabled=1\n" % (local_http_cache, puddle_director_pin_version)
    dest='/etc/yum.repos.d/rhos-release-8-director.repo'
    ssh.put_content(content, dest)

    print(ssh.run('subscription-manager register --username %s --password %s' % (rhsm_login, rhsm_password)))
    print(ssh.run('subscription-manager attach --auto'))
    subscription_cmd = "subscription-manager repos '--disable=*'"
    for repo in ['rhel-7-server-rpms', 'rhel-7-server-optional-rpms', 'enable=rhel-7-server-extras-rpms']:
        subscription_cmd += ' --enable='
        subscription_cmd +=  repo
    print(ssh.run(subscription_cmd))
    print(ssh.run('subscription-manager list'))
    print(ssh.run('yum install -y openstack-tripleo libguestfs-tools'))
    print(ssh.run('adduser -m stack'))
    ssh.put_content('stack ALL=(root) NOPASSWD:ALL\n', '/etc/sudoers.d/stack')
    print(ssh.run('mkdir -p /home/stack/.ssh'))
    print(ssh.run('cp /root/.ssh/authorized_keys /home/stack/.ssh/authorized_keys'))
    print(ssh.run('chown -R stack:stack /home/stack/.ssh'))
    print(ssh.run('chmod 700 /home/stack/.ssh'))
    print(ssh.run('chmod 600 /home/stack/.ssh/authorized_keys'))
    print(ssh.run('yum install -y libvirt-daemon-driver-nwfilter libvirt-client libvirt-daemon-config-network libvirt-daemon-driver-nodedev libvirt-daemon-kvm libvirt-python libvirt-daemon-config-nwfilter libvirt-daemon-driver-lxc libvirt-glib libvirt-daemon libvirt-daemon-driver-storage libvirt libvirt-daemon-driver-network libvirt-devel libvirt-gobject libvirt-daemon-driver-secret libvirt-daemon-driver-qemu libvirt-daemon-driver-interface libvirt-docs libguestfs-tools.noarch virt-install genisoimage qemu-img-rhev'))
    print(ssh.run('sed -i "s,#auth_unix_rw,auth_unix_rw," /etc/libvirt/libvirtd.conf'))
    print(ssh.run('systemctl start libvirtd'))
    print(ssh.run('systemctl status libvirtd'))
    print(ssh.run('mkdir -p /home/stack/DIB'))
    print(ssh.run('find /etc/yum.repos.d/ -type f -exec cp -v {} /home/stack/DIB \;'))
    print(ssh.run('mv /home/stack/DIB/redhat.repo /home/stack/DIB/rhos-release-rhel-7.2.repo'))
# NTP
    print(ssh.run('yum install -y yum-utils iptables libselinux-python psmisc redhat-lsb-core rsync'))
    print(ssh.run('systemctl disable NetworkManager'))
    print(ssh.run('systemctl stop NetworkManager'))
    print(ssh.run('pkill -9 dhclient'))
    print(ssh.run('yum remove -y cloud-init NetworkManager'))
    print(ssh.run('yum update -y'))
# reboot if a new initrd has been generated since the boot
    print(ssh.run('yum install -y yum-plugin-priorities python-tripleoclient python-rdomanager-oscplugin'))
    print(ssh.run('find /boot/ -anewer /proc/1/stat -name "initramfs*" -exec reboot \;'))

with SSHSession(ip, 'stack') as ssh:
    ssh.put_content('%s guest_image.qcow2\n' % guest_image_md5sum, 'guest_image.qcow2.md5')
    if ssh.run('md5sum -c /home/stack/guest_image.qcow2.md5')[1] != 0:
        print(ssh.run('curl -o /home/stack/guest_image.qcow2 http://%s/%s' % (local_http_cache, '/brewroot/packages/rhel-guest-image/7.2/20151102.0/images/rhel-guest-image-7.2-20151102.0.x86_64.qcow2')))

    from jinja2 import Environment, FileSystemLoader
    env = Environment()
    env.loader = FileSystemLoader('templates')
    template = env.get_template('virt-setup-env.j2')
    virt_setup_env = template.render(
        {
            'dib_dir': '/home/stack/DIB',
            'node': {
                'count': 3,
                'mem': 4096,
                'cpu': 2
            },
            'undercloud_node_mem': 4096,
            'guest_image_name': '/home/stack/guest_image.qcow2',
            'rhsm': {
                'user': rhsm_login,
                'password': rhsm_password
            },
            'product': {
            'repo_type': 'puddle'
        }})
    ssh.put_content(virt_setup_env, 'virt-setup-env')
    ssh.run('source virt-setup-env; instack-virt-setup')
    instack_ip = ssh.run('/sbin/ip n | grep $(tripleo get-vm-mac instack) | awk \'{print $1;}\'')[0]
    print(instack_ip)
