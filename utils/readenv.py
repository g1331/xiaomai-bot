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
        # 如果变量是一个列表，则将环境变量转换成列表并赋值给相应的变量
        if isinstance(config[var], list):
            env_value = os.environ.get(var, config[var][0])
            config[var] = env_value.split(",") if env_value else config[var]
        # 否则，直接将环境变量的值赋值给相应的变量
        else:
            config[var] = os.environ.get(var, config[var])

    # 写入更新后的配置文件
    output_path = os.path.join(root_path, 'config', 'config.yaml')
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True)