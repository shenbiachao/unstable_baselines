import os
import gym
import click
from common.logger import Logger
from sac.trainer import SACTrainer
from sac.model import SACAgent
from common.util import set_device, update_parameters, load_config
from common.buffer import ReplayBuffer
from sac.wrapper import SACWrapper
from  common import util

@click.command()
@click.argument("config-path",type=str)
@click.option("--log-dir", default="logs")
@click.option("--gpu", type=int, default=-1)
@click.option("--print-log", type=bool, default=True)
@click.option("--info", type=str, default="")
@click.argument('args', nargs=-1)
def main(config_path, log_dir, gpu, print_log,info, args):
    #load args
    args = load_config(config_path, args)
    #initialize device
    set_device(gpu)
    #initialize logger
    env_name = args['env_name']
    logger = Logger(log_dir, prefix = env_name+"-"+info, print_to_terminal=print_log)
    logger.log_str("logging to {}".format(logger.log_path))

    #save args
    logger.log_str_object("parameters", log_dict = args)

    #initialize environment
    logger.log_str("Initializing Environment")
    env = gym.make(env_name)
    env = SACWrapper(env, **args['env'])
    eval_env = gym.make(env_name)
    eval_env = SACWrapper(eval_env, **args['env'])
    state_space = env.observation_space
    action_space = env.action_space

    #initialize buffer
    logger.log_str("Initializing Buffer")
    buffer = ReplayBuffer(state_space, action_space, **args['buffer'])

    #initialize agent
    logger.log_str("Initializing Agent")
    agent = SACAgent(state_space, action_space, **args['agent'])

    #initialize trainer
    logger.log_str("Initializing Trainer")
    trainer  = SACTrainer(
        agent,
        env,
        eval_env,
        buffer,
        logger,
        **args['trainer']
    )

    
    logger.log_str("Started training")
    trainer.train()


if __name__ == "__main__":
    main()