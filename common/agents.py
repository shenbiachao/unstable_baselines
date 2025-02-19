from abc import abstractmethod
class BaseAgent(object):
    def __init__(self,**kwargs):
        super(BaseAgent,self).__init__(**kwargs)
    
    @abstractmethod
    def update(self,data_batch):
        pass

    @abstractmethod
    def select_action(self, state):
        pass

    @abstractmethod
    def load_model(self, dir):
        pass
    
    @abstractmethod
    def save_model(self, target_dir, ite):
        pass



class RandomAgent(BaseAgent):
    def __init__(self,observation_space, action_space, **kwargs):
        self.observation_space = observation_space
        self.action_space = action_space
        from common.networks import VNetwork
        self.v_network = VNetwork(observation_space.shape[0], 1, [64, 64], reparameterize=False)

    def update(self,data_batch, **kwargs):
        return


    def select_action(self, state, **kwargs):
        return self.action_space.sample()


    def act(self, state, evaluate=False):
        return self.action_space.sample(), 1.

    def load_model(self, dir, **kwargs):
        pass
    

    def save_model(self, target_dir, ite, **kwargs):
        pass