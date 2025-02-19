from common.buffer import ReplayBuffer, TDReplayBuffer
import numpy as np
from common import util
import torch
import random
from common import util

def rollout_trajectory(env, agent, max_traj_length):
    states, actions, log_pis, next_states, rewards, dones = [], [], [], [], [], []
    state = env.reset()
    done = False
    traj_length = 0
    while not done:
        action, log_pi = agent.select_action(state)
        #clipped_action = np.clip(action, env.action_space.low, env.action_space.high)
        #next_state, reward, done, info = env.step(clipped_action)
        next_state, reward, done, info = env.step(action)
        traj_length += 1
        timed_out = traj_length >= max_traj_length
        states.append(state)
        actions.append(action)
        log_pis.append(log_pi.item())
        next_states.append(next_state)
        rewards.append(reward)
        dones.append(done)
        state = next_state
        if done or traj_length >= max_traj_length:
            break
    return states, actions, log_pis, next_states, rewards, dones


class RolloutBuffer(object):
    def __init__(self, obs_space, action_space, 
                max_trajectories=-1, 
                max_env_steps=2048,  
                max_trajectory_length=1000, 
                n=1,  
                gamma=0.99, 
                gae_lambda=0.95,
                advantage_type="gae",
                normalize_advantage=True,
                **kwargs):
        self.n = n # parameter for td(n)
        self.max_buffer_size = max_trajectory_length + max_env_steps + 1
        max_buffer_size = self.max_buffer_size
        self.max_trajectory_length = max_trajectory_length
        self.max_trajectories = np.inf if max_trajectories == -1 else max_trajectories
        self.max_env_steps = max_env_steps
        self.gamma = gamma
        self.obs_dim = obs_space.shape[0]
        self.action_dim = action_space.shape[0]
        self.obs_buffer = np.zeros((max_buffer_size, self.obs_dim)).astype(float)
        self.next_obs_buffer = np.zeros((self.max_buffer_size, self.obs_dim)).astype(float)
        self.action_buffer = np.zeros((max_buffer_size, self.action_dim))
        self.log_pi_buffer = np.zeros((max_buffer_size,)).astype(float)
        self.reward_buffer = np.zeros((max_buffer_size,)).astype(float)
        self.done_buffer = np.zeros((max_buffer_size,)).astype(float)
        self.return_buffer = np.zeros((max_buffer_size,)).astype(float)# calculate return for the whole trajectory
        self.advantage_buffer = np.zeros((max_buffer_size,)).astype(float)# calculate return for the whole trajectory
        #insert a random state at initialization to avoid bugs when inserting the first state
        self.max_sample_size = 0
        self.curr = 0
        self.finalized = False
        self.normalize_advantage = normalize_advantage
        self.advantage_type = advantage_type
        self.gae_lambda = gae_lambda
        self.path_start_idx = 0
    @property
    def size(self):
        return self.max_sample_size

    def collect_trajectories(self, env, agent, value_network, gae_lambda=0.8):
        if self.finalized:
            print("collecting for a finalized rollout, resetting the rollout")
            self.reset()
        self.gae_lambda = gae_lambda
        traj_rewards = []
        traj_lengths = []
        tot_env_steps = 0
        tot_trajectories = 0
        while(tot_trajectories < self.max_trajectories):
            with torch.no_grad():
                states, actions, log_pis, next_states, rewards, dones = rollout_trajectory(env, agent, self.max_trajectory_length)
            self.add_traj(states, actions,log_pis, next_states, rewards, dones)
            #finish computing of the advantage and return
            self.finish_traj(value_network)

            tot_env_steps += len(states)
            traj_rewards.append(np.sum(rewards))
            traj_lengths.append(len(states))

            tot_trajectories += 1
            if tot_env_steps > self.max_env_steps:
                break
        
        with torch.no_grad():
            self.finalize(agent.v_network) #convert to tensor type, calculate all return to go

        return np.mean(traj_rewards), np.mean(traj_lengths)


    def finish_traj(self, value_network):
        path_slice = slice(self.path_start_idx, self.curr)
        obs = torch.FloatTensor(self.obs_buffer[path_slice]).to(util.device)
        values = value_network(obs).detach().cpu().numpy().flatten()
        if self.done_buffer[self.curr - 1]:
            last_val = 0.
        else:#timeout case
            last_obs = torch.Tensor([self.next_obs_buffer[self.curr - 1]])
            last_val = value_network(last_obs).detach().cpu().numpy()[0]
        rews = np.append(self.reward_buffer[path_slice], last_val)
        values = np.append(values, last_val)
        # the next two lines implement GAE-Lambda advantage calculation
        deltas = rews[:-1] + self.gamma * values[1:] - values[:-1]
        self.advantage_buffer[path_slice] = util.discount_cum_sum(deltas, self.gamma * self.gae_lambda)
        
        # the next line computes rewards-to-go, to be targets for the value function
        self.return_buffer[path_slice] = util.discount_cum_sum(rews, self.gamma)[:-1]
        self.path_start_idx = self.curr

    def reset(self):
        #delete buffers
        del self.obs_buffer, self.action_buffer, self.log_pi_buffer, self.reward_buffer, self.done_buffer,\
             self.next_obs_buffer, self.return_buffer, self.advantage_buffer#, self.value_buffer

        self.obs_buffer = np.zeros((self.max_buffer_size, self.obs_dim)).astype(float)
        self.next_obs_buffer = np.zeros((self.max_buffer_size, self.obs_dim)).astype(float)
        self.action_buffer = np.zeros((self.max_buffer_size, self.action_dim))
        self.log_pi_buffer = np.zeros((self.max_buffer_size,)).astype(float)
        self.reward_buffer = np.zeros((self.max_buffer_size,)).astype(float)
        self.done_buffer = np.zeros((self.max_buffer_size,)).astype(float)
        self.return_buffer = np.zeros((self.max_buffer_size,)).astype(float)# calculate return for the whole trajectory
        self.advantage_buffer = np.zeros((self.max_buffer_size,)).astype(float)# calculate return for the whole trajectory
        self.max_sample_size = 0
        self.curr = 0
        self.path_start_idx = 0
        self.finalized = False

    def add_traj(self, obs_list, action_list, log_pi_list, next_obs_list, reward_list, done_list, ):
        for obs, action, log_pi, next_obs, reward, done  in zip(obs_list, action_list, log_pi_list, next_obs_list, reward_list, done_list):
            self.add_tuple(obs, action, log_pi, next_obs, reward, done)
    
    def add_tuple(self, obs, action, log_pi, next_obs, reward, done):
        # store to instant memories
        self.obs_buffer[self.curr] = np.array(obs).copy()
        self.action_buffer[self.curr] = np.array(action)
        self.log_pi_buffer[self.curr] = np.array(log_pi)
        self.next_obs_buffer[self.curr] = np.array(next_obs)
        self.reward_buffer[self.curr] = np.array(reward)
        self.done_buffer[self.curr] = np.array(done)
        self.curr = (self.curr+1) % self.max_buffer_size
        self.max_sample_size = min(self.max_sample_size + 1, self.max_buffer_size)

    
    def finalize(self, value_network):
        self.obs_buffer = torch.FloatTensor(self.obs_buffer[:self.max_sample_size]).to(util.device)
        self.next_obs_buffer = torch.FloatTensor(self.next_obs_buffer[:self.max_sample_size]).to(util.device)
        #convert the remaining buffers to tensor and pass data to device
        self.reward_buffer = torch.FloatTensor(self.reward_buffer[:self.max_sample_size]).to(util.device)
        #self.value_buffer = torch.FloatTensor(self.value_buffer[:self.max_sample_size]).to(util.device).unsqueeze(1)
        self.action_buffer = torch.FloatTensor(self.action_buffer[:self.max_sample_size]).to(util.device)
        self.log_pi_buffer = torch.FloatTensor(self.log_pi_buffer[:self.max_sample_size]).to(util.device).unsqueeze(1)
        self.advantage_buffer = torch.FloatTensor(self.advantage_buffer[:self.max_sample_size]).to(util.device).unsqueeze(1)
        self.return_buffer = torch.FloatTensor(self.return_buffer[:self.max_sample_size]).to(util.device).unsqueeze(1)
        #self.done_buffer = torch.FloatTensor(self.done_buffer[:self.max_sample_size]).to(util.device).unsqueeze(1)
        self.finalized = True

    def sample_batch(self, batch_size, to_tensor = True, step_size: int = 1):
        # batch_size: 
        # to_tensor: if convert to torch.tensor type as pass to util.device
        # step_size: return a list of next states, returns and dones with size n
        if not self.finalized:
            print("sampling before finalizing the buffer")
            assert 0
        
        batch_size = min(self.max_sample_size, batch_size)
        index = random.sample(range(self.max_sample_size), batch_size)
        obs_batch, action_batch, log_pi_batch, next_obs_batch, reward_batch, advantage_batch, return_batch, done_batch = \
            self.obs_buffer[index], \
            self.action_buffer[index],\
            self.log_pi_buffer[index],\
            self.next_obs_buffer[index],\
            self.reward_buffer[index],\
            self.advantage_buffer[index],\
            self.return_buffer[index],\
            self.done_buffer[index]
        return obs_batch, action_batch, log_pi_batch, next_obs_batch, reward_batch, advantage_batch, return_batch, done_batch


    def print_buffer_helper(self, nme, lst, summarize=False, print_curr_ptr = False):
        if type(lst) == torch.Tensor:
            lst = lst.detach().cpu().numpy()
        #for test purpose
        #print(type(lst), self.max_sample_size)
        str_to_print = ""
        for i in range(self.max_sample_size):
            if print_curr_ptr:
                str_to_print += "^\t" if self.curr - 1 == i else "\t"  
            elif summarize:
                str_to_print += "{:.02f}\t".format(np.mean(lst[i]))
            else:
                str_to_print += "{:.02f}\t".format(lst[i])
        print("{}:\t{}" .format(nme, str_to_print))

    def print_buffer(self):
        #for test purpose
        self.print_buffer_helper("o",self.obs_buffer, summarize=True)
        #self.print_buffer_helper("a",self.action_buffer, summarize=True)
        self.print_buffer_helper("nxt_o",self.next_obs_buffer, summarize=True)
        self.print_buffer_helper("r",self.reward_buffer, summarize=True)
        self.print_buffer_helper("ret",self.return_buffer, summarize=True)
        self.print_buffer_helper("value",self.value_buffer, summarize=True)
        self.print_buffer_helper("adv",self.advantage_buffer, summarize=True)
        self.print_buffer_helper("done",self.done_buffer, summarize=True)
        self.print_buffer_helper("index", None, print_curr_ptr=True)
        print("\n")
    
    

if __name__ == "__main__":
    from tqdm import tqdm
    import gym
    from common.agents import RandomAgent


    #code for testing td buffer
    env = gym.make("HalfCheetah-v2")
    #env = gym.make("CartPole-v1")
    obs_space = env.observation_space
    action_space = env.action_space
    n = 1
    gamma = 0.5
    max_buffer_size = 12
    max_traj_length = 5
    num_trajs = 4
    agent = RandomAgent(obs_space, action_space)
    rollout_buffer = RolloutBuffer(obs_space=obs_space,
                        action_space=action_space,
                        max_trajectory_length=max_traj_length,
                        gamma=gamma,
                        n=n,
                        max_env_steps=max_buffer_size,
                        advantage_type="gae")
    
    l, r = rollout_buffer.collect_trajectories(env, agent,n=n)
    rollout_buffer.print_buffer()