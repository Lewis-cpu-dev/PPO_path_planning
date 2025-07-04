import torch
import torch.nn as nn
from utils import v_wrap, set_init, push_and_pull, record, SharedAdam
import torch.nn.functional as F
import torch.multiprocessing as mp
import gym
import os
from column_env import RandomObstaclesEnv
from network import Net
os.environ["OMP_NUM_THREADS"] = "1"

UPDATE_GLOBAL_ITER = 10
GAMMA = 0.99
MAX_EP = 30000

env = RandomObstaclesEnv()
N_S = env.observation_space.shape
N_A = env.action_space.n



class Worker(mp.Process):
    def __init__(self, gnet, opt, global_ep, global_ep_r, res_queue, name):
        super(Worker, self).__init__()
        self.name = 'w%02i' % name
        self.g_ep, self.g_ep_r, self.res_queue = global_ep, global_ep_r, res_queue
        self.gnet, self.opt = gnet, opt
        self.lnet = Net(N_S, N_A)           # local network
        self.env = RandomObstaclesEnv().unwrapped

    def run(self):
        total_step = 1
        while self.g_ep.value < MAX_EP:
            s = self.env.reset()[0]
            buffer_s, buffer_a, buffer_r = [], [], []
            ep_r = 0.
            action_list = []
            max_steps_per_ep = 200
            step_in_ep = 0
            while True:                 
                if self.name == 'w00':
                    pass#self.env.render()

                a = self.lnet.choose_action(v_wrap(s[None, :]))[0]
                
                action_list.append(str(a))
                
                s_, r, done, trancated, _ = self.env.step(a)
                if done: r = 0
                ep_r += r
                buffer_a.append(a)
                buffer_s.append(s)
                buffer_r.append(r)

                if total_step % UPDATE_GLOBAL_ITER == 0 or done or step_in_ep >= max_steps_per_ep:  # update global and assign to local net
                    # sync
                    push_and_pull(self.opt, self.lnet, self.gnet, done, s_, buffer_s, buffer_a, buffer_r, GAMMA)
                    buffer_s, buffer_a, buffer_r = [], [], []

                    if done or step_in_ep >= max_steps_per_ep:  # done and print information
                        with open('action_file', 'a') as f:
    # Iterate over each element in the list
                            for item in action_list:
                                f.write(item + ' ')
                            f.write('\n')
                        record(self.g_ep, self.g_ep_r, ep_r, self.res_queue, self.name)
                        break
                s = s_
                total_step += 1
                step_in_ep +=1
        self.res_queue.put(None)


if __name__ == "__main__":
    gnet = Net(N_S, N_A)        # global network
    gnet.share_memory()         # share the global parameters in multiprocessing
    opt = SharedAdam(gnet.parameters(), lr=1e-6, betas=(0.92, 0.999))      # global optimizer
    global_ep, global_ep_r, res_queue = mp.Value('i', 0), mp.Value('d', 0.), mp.Queue()

    # parallel training
    workers = [Worker(gnet, opt, global_ep, global_ep_r, res_queue, i) for i in range(mp.cpu_count())]
    [w.start() for w in workers]
    res = []                    # record episode reward to plot
    while True:
        r = res_queue.get()
        if r is not None:
            res.append(r)
        else:
            break
    [w.join() for w in workers]

    import matplotlib.pyplot as plt
    plt.plot(res)
    plt.ylabel('Moving average ep reward')
    plt.xlabel('Step')
    plt.show()