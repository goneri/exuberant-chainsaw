#!/usr/bin/env python3

import os
import time
import glanceclient.v2.client
import keystoneclient
import keystoneclient.v2_0.client
import novaclient.client

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


## prints a list with all users
#tenants = keystone.services.list()
#print(tenants)

# prints a list with all flavors
flavors = nova.flavors.list()
print(flavors)

# print the list of all running instances
servers = nova.servers.list()
print(servers)

# prints the list of all keypairs
keypairs = nova.keypairs.list()
print(keypairs)

# Start the Hypervisor
server = nova.servers.create('bob',
                    get_id(nova, 'image', name='RHEL 7.2 x86_64'),
                    flavor=get_id(nova, 'flavor', name='m1.small'),
                    key_name='DCI',
                    nics=[{'net-id': get_id(nova, 'network', label='public')}])
#server = nova.servers.get('e9b744b2-a450-4526-a03b-1250044ac194')

for i in range(0, 120):
    print(server.status)
    if server.status == 'ACTIVE':
        print("Server started in about %s seconds." % i)
        break
    if server.status == 'ERROR':
        print("nova boot has failed")
        print(server.diagnostics())
        break
    if i % 10 == 0:
        server = nova.servers.get(server.id)
    time.sleep(1)
floating_ip = get_floating_ip(nova)
server.add_floating_ip(floating_ip.id)
server.add_security_group('ssh')
server.add_security_group('rhos-mirror-user')

ips = nova.servers.ips(server)

print(ips)
import paramiko
client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(floating_ip.ip, 22, 'cloud-user')
stdin, stdout, stderr = client.exec_command('ls')
print(stdout.read())
client.close()
