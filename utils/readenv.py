import os
import yaml

env_vars = ["bot_accounts", "default_account", "Master", "mirai_host", "verify_key", "test_group", "db_link"]
root_path = os.getcwd()

def read_env():
    return all(os.environ.get(var) for var in env_vars)

def save_env_2_config():
    config_path = os.path.join(root_path, 'config', 'config_demo.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 更新变量的值
    for var in env_vars:
        if isinstance(config[var], list):
            config[var][0] = [int(x) for x in os.environ.get(var, config[var][0]).split(',')]
        else:
            if config[var].isdigit():
                config[var] = int(os.environ.get(var, config[var]))
            else:
                config[var] = os.environ.get(var, config[var])

    # 写入更新后的配置文件
    output_path = os.path.join(root_path, 'config', 'config.yaml')
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True)