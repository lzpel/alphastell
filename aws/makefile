export MSYS_NO_PATHCONV := 1

node_modules: package.json
	npm install

bootstrap: node_modules
	npx cdk bootstrap

synth: node_modules
	npx cdk synth

diff: node_modules
	npx cdk diff

deploy: node_modules
	npx cdk deploy --require-approval never --all

destroy: node_modules
	npx cdk destroy --force --all

clean:
	rm -rf cdk.out node_modules
