import os
HOST_ACCOUNT = os.environ.get('MR_HOST_ACCOUNT', 'martyr')
print(f'HOST: {HOST_ACCOUNT}')
clean_host = (HOST_ACCOUNT or '').strip(' "\'').lower()
print(f'CLEAN HOST: {clean_host}')
