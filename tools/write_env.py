import pathlib,os
p=pathlib.Path(__file__).resolve().parents[1]
values={'POSTGRES_PASSWORD':(p/'.secrets/postgres_password').read_text().strip(),'INTERNAL_SERVICE_TOKEN':(p/'.secrets/service_token').read_text().strip()}
f=p/'.env';fd=os.open(f,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as out:
 for k,v in values.items():out.write(k+'='+v+'\n')
print('Compose environment written securely')
