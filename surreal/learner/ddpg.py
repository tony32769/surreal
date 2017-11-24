import torch
import torch.nn as nn

import surreal.utils as U
from surreal.model.ddpg_net import DDPGModel
from .base import Learner

from tensorboardX import SummaryWriter


class DDPGLearner(Learner):

    def __init__(self, learn_config, env_config, session_config):
        super().__init__(learn_config, env_config, session_config)

        self.discount_factor = 0.99
        self.tau = 0.01

        self.action_dim = self.env_config.action_spec.dim[0]
        self.obs_dim = self.env_config.obs_spec.dim[0]

        self.model = DDPGModel(
            obs_dim=self.obs_dim,
            action_dim=self.action_dim,
        )

        self.model_target = DDPGModel(
            obs_dim=self.obs_dim,
            action_dim=self.action_dim,
        )

        self.critic_criterion = nn.MSELoss()

        self.critic_optim = torch.optim.Adam(
            self.model.critic.parameters(),
            lr=1e-3
        )

        self.actor_optim = torch.optim.Adam(
            self.model.actor.parameters(),
            lr=1e-4
        )

        U.hard_update(self.model_target.actor, self.model.actor)
        U.hard_update(self.model_target.critic, self.model.critic)

        self.train_iteration = 0
        self.writer = SummaryWriter()

    def _optimize(self, obs, actions, rewards, obs_next, done):

        assert actions.max().data[0] <= 1.0
        assert actions.min().data[0] >= -1.0

        # estimate rewards using the next state: r + argmax_a Q'(s_{t+1}, u'(a))
        # obs_next.volatile = True
        next_actions_target = self.model_target.forward_actor(obs_next)

        # obs_next.volatile = False
        next_Q_target = self.model_target.forward_critic(obs_next, next_actions_target)
        # next_Q_target.volatile = False
        y = rewards + self.discount_factor * next_Q_target * (1.0 - done)
        y = y.detach()

        # compute Q(s_t, a_t)
        y_policy = self.model.forward_critic(
            obs.detach(),
            actions.detach()
        )

        # critic update
        self.model.critic.zero_grad()
        critic_loss = self.critic_criterion(y_policy, y)
        critic_loss.backward()
        # for p in self.model.critic.parameters():
        #     p.grad.data.clamp_(-5.0, 5.0)
        self.critic_optim.step()

        # actor update
        self.model.actor.zero_grad()
        actor_loss = -self.model.forward_critic(
            obs.detach(),
            self.model.forward_actor(obs.detach())
        ).mean()
        actor_loss.backward()
        # for p in self.model.actor.parameters():
        #     p.grad.data.clamp_(-5.0, 5.0)
        self.actor_optim.step()

        # emit summaries
        if self.writer:
            self.writer.add_scalar('actor_loss', actor_loss.data[0], self.train_iteration)
            self.writer.add_scalar('critic_loss', critic_loss.data[0], self.train_iteration)
            self.writer.add_scalar('action_norm', actions.norm(2, 1).mean().data[0], self.train_iteration)
            self.writer.add_scalar('rewards', rewards.mean().data[0], self.train_iteration)
            self.writer.add_scalar('Q_target', y.mean().data[0], self.train_iteration)
            self.writer.add_scalar('Q_policy', y_policy.mean().data[0], self.train_iteration)

        # soft update target networks
        U.soft_update(self.model_target.actor, self.model.actor, self.tau)
        U.soft_update(self.model_target.critic, self.model.critic, self.tau)

        self.train_iteration += 1

    def learn(self, batch):
        self._optimize(
            batch.obs,
            batch.actions,
            batch.rewards,
            batch.obs_next,
            batch.dones
        )

    def module_dict(self):
        return {
            'ddpg': self.model,
        }