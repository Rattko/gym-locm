import gym
import numpy as np

from gym_locm.agents import RandomDraftAgent, RandomBattleAgent
from gym_locm.engine import State, Phase, Action, PlayerOrder
from gym_locm.envs.base_env import LOCMEnv
from gym_locm.exceptions import GameIsEndedError, MalformedActionError


class LOCMBattleEnv(LOCMEnv):
    metadata = {'render.modes': ['text', 'native']}

    def __init__(self,
                 draft_agents=(RandomDraftAgent(), RandomDraftAgent()),
                 seed=None):
        super().__init__(seed=seed)

        self.draft_agents = draft_agents

        for draft_agent in self.draft_agents:
            draft_agent.reset()
            draft_agent.seed(seed)

        cards_in_state = 8 + 6 + 6  # 20 cards
        card_features = 16
        player_features = 4  # hp, mana, next_rune, next_draw

        # 328 features
        self.state_shape = player_features * 2 + cards_in_state * card_features
        self.observation_space = gym.spaces.Box(
            low=-1.0, high=1.0, shape=(self.state_shape,), dtype=np.float32
        )

        # 163 possible actions
        self.action_space = gym.spaces.Discrete(163)

        # reset all agents' internal state
        for agent in self.draft_agents:
            agent.reset()

        # play through draft
        while self.state.phase == Phase.DRAFT:
            for agent in self.draft_agents:
                action = agent.act(self.state)

                self.state.act(action)

    def step(self, action):
        """Makes an action in the game."""
        # if the battle is finished, there should be no more actions
        if self._battle_is_finished:
            raise GameIsEndedError()

        # check if an action object or an integer was passed
        if not isinstance(action, Action):
            try:
                action = int(action)
            except ValueError:
                error = f"Action should be an action object " \
                    f"or an integer, not {type(action)}"

                raise MalformedActionError(error)

            action = self.decode_action(action)

        # less property accesses
        state = self.state

        # execute the action
        state.act(action)

        # build return info
        winner = state.winner

        reward = 0
        done = state.winner is not None
        info = {'phase': state.phase,
                'turn': state.turn,
                'winner': state.winner}

        if winner is not None:
            reward = 1 if winner == PlayerOrder.FIRST else -1

            del info['turn']

        return self._encode_state(), reward, done, info

    def reset(self) -> np.array:
        """
        Resets the environment.
        The game is put into its initial state and all agents are reset.
        """
        # reset the state
        super().reset()

        # reset all agents' internal state
        for agent in self.draft_agents:
            agent.reset()
            agent.seed(self._seed)

        # play through draft
        while self.state.phase == Phase.DRAFT:
            for agent in self.draft_agents:
                self.state.act(agent.act(self.state))

        return self._encode_state()

    def _encode_state_draft(self):
        pass

    def _encode_state_battle(self):
        encoded_state = np.full(self.state_shape, 0, dtype=np.float32)

        p0, p1 = self.state.current_player, self.state.opposing_player

        dummy_card = [0] * 16

        def fill_cards(card_list, up_to):
            remaining_cards = up_to - len(card_list)

            return card_list + [dummy_card for _ in range(remaining_cards)]

        all_cards = []

        locations = p0.hand, p0.lanes[0], p0.lanes[1], p1.lanes[0], p1.lanes[1]
        card_limits = 8, 3, 3, 3, 3

        for location, card_limit in zip(locations, card_limits):
            # convert all cards to features
            location = list(map(self.encode_card, location))

            # add dummy cards up to the card limit
            location = fill_cards(location, up_to=card_limit)

            # add to card list
            all_cards.extend(location)

        # players info
        encoded_state[:8] = self.encode_players(p0, p1)
        encoded_state[8:] = np.array(all_cards).flatten()

        return encoded_state


class LOCMBattleSingleEnv(LOCMBattleEnv):
    def __init__(self, battle_agent=RandomBattleAgent(),
                 play_first=True, **kwargs):
        # init the env
        super().__init__(**kwargs)

        # also init the battle agent and the new parameter
        self.battle_agent = battle_agent
        self.play_first = play_first

    def reset(self) -> np.array:
        """
        Resets the environment.
        The game is put into its initial state and all agents are reset.
        """
        # reset what is needed
        encoded_state = super().reset()

        # also reset the battle agent
        self.battle_agent.reset()

        # if playing second, have first player play
        if not self.play_first:
            while self.state.current_player.id != PlayerOrder.SECOND:
                super().step(self.battle_agent.act(self.state))

        return encoded_state

    def step(self, action):
        """Makes an action in the game."""
        player = self.state.current_player.id

        # do the action
        result = super().step(action)

        # have opponent play until its player's turn or there's a winner
        while self.state.current_player.id != player and self.state.winner is None:
            result = super().step(self.battle_agent.act(self.state))

        return result


class LOCMBattleSelfPlayEnv(LOCMBattleEnv):
    def __init__(self, play_first=True, **kwargs):
        # init the env
        super().__init__(**kwargs)

        # also init the new parameters
        self.play_first = play_first
        self.model = None

    def set_model(self, model_builder, env_builder):
        self.model = model_builder(env_builder(self))

    def update_parameters(self, parameters):
        """Update the current parameters in the model with new ones."""
        self.model.load_parameters(parameters, exact_match=True)

    def step(self, action):
        """Makes an action in the game."""
        obs = self._encode_state()

        # act according to first and second players
        if self.play_first:
            super().step(action)
            result = super().step(self.model.predict(obs)[0])
        else:
            super().step(self.model.predict(obs)[0])
            result = super().step(action)

        return result
