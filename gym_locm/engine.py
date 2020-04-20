import sys

import numpy as np

from typing import List, Tuple
from enum import Enum, IntEnum

from gym.utils import seeding

from gym_locm.exceptions import *
from gym_locm.helpers import has_enough_mana, is_it


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


class Phase(IntEnum):
    DRAFT = 0
    BATTLE = 1
    ENDED = 2


class PlayerOrder(IntEnum):
    FIRST = 0
    SECOND = 1

    def opposing(self):
        return PlayerOrder((self + 1) % 2)


class Lane(IntEnum):
    LEFT = 0
    RIGHT = 1


class ActionType(Enum):
    PICK = 0
    SUMMON = 1
    ATTACK = 2
    USE = 3
    PASS = 4


class Location(IntEnum):
    PLAYER_HAND = 0
    ENEMY_HAND = 1

    PLAYER_BOARD = 10
    PLAYER_LEFT_LANE = 10
    PLAYER_RIGHT_LANE = 11

    ENEMY_BOARD = 20
    ENEMY_LEFT_LANE = 20
    ENEMY_RIGHT_LANE = 21


class Player:
    def __init__(self, player_id):
        self.id = player_id

        self.health = 30
        self.base_mana = 0
        self.bonus_mana = 0
        self.mana = 0
        self.next_rune = 25
        self.bonus_draw = 0

        self.last_drawn = 0

        self.deck = []
        self.hand = []
        self.lanes = ([], [])

        self.actions = []

    def draw(self, amount: int = 1):
        for _ in range(amount):
            if len(self.deck) == 0:
                raise EmptyDeckError()

            if len(self.hand) >= 8:
                raise FullHandError()

            self.hand.append(self.deck.pop())

    def damage(self, amount: int) -> int:
        self.health -= amount

        while self.health <= self.next_rune and self.next_rune > 0:
            self.next_rune -= 5
            self.bonus_draw += 1

        return amount

    def clone(self):
        cloned_player = Player.empty_copy()

        cloned_player.id = self.id
        cloned_player.health = self.health
        cloned_player.base_mana = self.base_mana
        cloned_player.bonus_mana = self.bonus_mana
        cloned_player.mana = self.mana
        cloned_player.next_rune = self.next_rune
        cloned_player.bonus_draw = self.bonus_draw

        cloned_player.deck = [card.make_copy(card.instance_id)
                              for card in self.deck]
        cloned_player.hand = [card.make_copy(card.instance_id)
                              for card in self.hand]
        cloned_player.lanes = tuple([[card.make_copy(card.instance_id)
                                      for card in lane]
                                     for lane in self.lanes])

        cloned_player.actions = list(self.actions)

        return cloned_player

    @staticmethod
    def empty_copy():
        class Empty(Player):
            def __init__(self):
                pass

        new_copy = Empty()
        new_copy.__class__ = Player

        return new_copy


class Card:
    def __init__(self, card_id, name, card_type, cost, attack, defense, keywords,
                 player_hp, enemy_hp, card_draw, text, instance_id=None):
        self.id = card_id
        self.instance_id = instance_id
        self.name = name
        self.type = card_type
        self.cost = cost
        self.attack = attack
        self.defense = defense
        self.keywords = set(list(keywords.replace("-", "")))
        self.player_hp = player_hp
        self.enemy_hp = enemy_hp
        self.card_draw = card_draw
        self.text = text

    def has_ability(self, keyword: str) -> bool:
        return keyword in self.keywords

    def make_copy(self, instance_id=None) -> 'Card':
        cloned_card = Card.empty_copy(self)

        cloned_card.id = self.id
        cloned_card.name = self.name
        cloned_card.type = self.type
        cloned_card.cost = self.cost
        cloned_card.attack = self.attack
        cloned_card.defense = self.defense
        cloned_card.keywords = set(self.keywords)
        cloned_card.player_hp = self.player_hp
        cloned_card.enemy_hp = self.enemy_hp
        cloned_card.card_draw = self.card_draw
        cloned_card.text = self.text

        if instance_id is not None:
            cloned_card.instance_id = instance_id
        else:
            cloned_card.instance_id = None

        return cloned_card

    def __eq__(self, other):
        return other is not None \
               and self.instance_id is not None \
               and other.instance_id is not None \
               and self.instance_id == other.instance_id

    def __repr__(self):
        if self.name:
            return f"({self.instance_id}: {self.name})"
        else:
            return f"({self.instance_id})"

    @staticmethod
    def empty_copy(card):
        class Empty(Card):
            def __init__(self):
                pass

        new_copy = Empty()
        new_copy.__class__ = type(card)

        return new_copy


class Creature(Card):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.is_dead = False
        self.can_attack = False
        self.has_attacked_this_turn = False

    def remove_ability(self, ability: str):
        self.keywords.discard(ability)

    def add_ability(self, ability: str):
        self.keywords.add(ability)

    def able_to_attack(self) -> bool:
        return not self.has_attacked_this_turn and \
               (self.can_attack or self.has_ability('C'))

    def damage(self, amount: int = 1, lethal: bool = False) -> int:
        if amount <= 0:
            return 0

        if self.has_ability('W'):
            self.remove_ability('W')

            raise WardShieldError()

        self.defense -= amount

        if lethal or self.defense <= 0:
            self.is_dead = True

        return amount

    def make_copy(self, instance_id=None) -> 'Card':
        cloned_card = super().make_copy(instance_id)

        cloned_card.is_dead = self.is_dead
        cloned_card.can_attack = self.can_attack
        cloned_card.has_attacked_this_turn = self.has_attacked_this_turn

        return cloned_card


class Item(Card):
    pass


class GreenItem(Item):
    pass


class RedItem(Item):
    pass


class BlueItem(Item):
    pass


class Action:
    def __init__(self, action_type, origin=None, target=None):
        self.type = action_type
        self.origin = origin
        self.target = target

    def __eq__(self, other):
        return other is not None and \
               self.type == other.type and \
               self.origin == other.origin and \
               self.target == other.target

    def __repr__(self):
        return f"{self.type} {self.origin} {self.target}"


def load_cards() -> List['Card']:
    cards = []

    with open('gym_locm/cardlist.txt', 'r') as card_list:
        raw_cards = card_list.readlines()
        type_mapping = {'creature': Creature, 'itemRed': RedItem,
                        'itemGreen': GreenItem, 'itemBlue': BlueItem}

        for card in raw_cards:
            card_id, name, card_type, cost, attack, defense, \
                keywords, player_hp, enemy_hp, card_draw, text = \
                map(str.strip, card.split(';'))

            card_class = type_mapping[card_type]

            cards.append(card_class(int(card_id), name, card_type, int(cost),
                                    int(attack), int(defense), keywords,
                                    int(player_hp), int(enemy_hp),
                                    int(card_draw), text))

    assert len(cards) == 160

    return cards


_cards = load_cards()


class State:
    __available_actions_draft = (
        Action(ActionType.PICK, 0),
        Action(ActionType.PICK, 1),
        Action(ActionType.PICK, 2)
    )

    def __init__(self, seed=None, items=True):
        self.instance_counter = 0

        self.np_random = None
        self.seed(seed)
        self.items = items

        self.phase = Phase.DRAFT
        self.turn = 1
        self.was_last_action_invalid = False
        self.players = (Player(PlayerOrder.FIRST), Player(PlayerOrder.SECOND))
        self._current_player = PlayerOrder.FIRST
        self.__available_actions = None
        self.__action_mask = None

        self.winner = None

        self._draft_cards = self._new_draft()

        current_draft_choices = self._draft_cards[self.turn - 1]

        for player in self.players:
            player.hand = current_draft_choices

    @property
    def current_player(self) -> Player:
        return self.players[self._current_player]

    @property
    def opposing_player(self) -> Player:
        return self.players[(int(self._current_player) + 1) % 2]

    @property
    def available_actions(self) -> Tuple[Action]:
        if self.__available_actions is not None:
            return self.__available_actions

        if self.phase == Phase.DRAFT:
            self.__available_actions = self.__available_actions_draft
        elif self.phase == Phase.ENDED:
            self.__available_actions = ()
        else:
            summon, attack, use = [], [], []

            c_hand = self.current_player.hand
            c_lanes = self.current_player.lanes
            o_lanes = self.opposing_player.lanes

            for card in filter(has_enough_mana(self.current_player.mana), c_hand):
                origin = card.instance_id

                if isinstance(card, Creature):
                    for lane in Lane:
                        if len(c_lanes[lane]) < 3:
                            summon.append(Action(ActionType.SUMMON, origin, lane))

                elif isinstance(card, GreenItem):
                    for lane in Lane:
                        for friendly_creature in c_lanes[lane]:
                            target = friendly_creature.instance_id

                            use.append(Action(ActionType.USE, origin, target))

                elif isinstance(card, RedItem):
                    for lane in Lane:
                        for enemy_creature in o_lanes[lane]:
                            target = enemy_creature.instance_id

                            use.append(Action(ActionType.USE, origin, target))

                elif isinstance(card, BlueItem):
                    for lane in Lane:
                        for enemy_creature in o_lanes[lane]:
                            target = enemy_creature.instance_id

                            use.append(Action(ActionType.USE, origin, target))

                    use.append(Action(ActionType.USE, origin, None))

            for lane in Lane:
                guard_creatures = []

                for enemy_creature in o_lanes[lane]:
                    if enemy_creature.has_ability('G'):
                        guard_creatures.append(enemy_creature)

                if not guard_creatures:
                    valid_targets = o_lanes[lane] + [None]
                else:
                    valid_targets = guard_creatures

                for friendly_creature in filter(Creature.able_to_attack,
                                                c_lanes[lane]):
                    origin = friendly_creature.instance_id

                    for valid_target in valid_targets:
                        if valid_target is not None:
                            valid_target = valid_target.instance_id

                        attack.append(Action(ActionType.ATTACK, origin, valid_target))

            available_actions = summon + attack + use

            if not available_actions:
                available_actions = [Action(ActionType.PASS)]

            self.__available_actions = tuple(available_actions)

        return self.__available_actions

    @property
    def action_mask(self):
        if self.__action_mask is not None:
            return self.__action_mask

        if self.phase == Phase.DRAFT:
            return [1, 1, 1]
        elif self.phase == Phase.ENDED:
            return [0] * (145 if self.items else 41)

        action_mask = [0] * 145

        # pass is always allowed
        action_mask[0] = 1

        # shortcuts
        cp, op = self.current_player, self.opposing_player
        cp_has_enough_mana = has_enough_mana(cp.mana)
        left_lane_not_full = len(cp.lanes[0]) < 3
        right_lane_not_full = len(cp.lanes[1]) < 3

        def validate_creature(index):
            if left_lane_not_full:
                action_mask[1 + index * 2] = 1

            if right_lane_not_full:
                action_mask[1 + index * 2 + 1] = 1

        def validate_green_item(index):
            for i in range(len(cp.lanes[0])):
                action_mask[17 + index * 13 + 1 + i] = 1

            for i in range(len(cp.lanes[1])):
                action_mask[17 + index * 13 + 4 + i] = 1

        def validate_red_item(index):
            for i in range(len(op.lanes[0])):
                action_mask[17 + index * 13 + 7 + i] = 1

            for i in range(len(op.lanes[1])):
                action_mask[17 + index * 13 + 10 + i] = 1

        def validate_blue_item(index):
            validate_red_item(index)

            action_mask[17 + index * 13] = 1

        check_playability = {
            Creature: validate_creature,
            GreenItem: validate_green_item,
            RedItem: validate_red_item,
            BlueItem: validate_blue_item
        }

        # for each card in hand, check valid actions
        for i, card in enumerate(cp.hand):
            if cp_has_enough_mana(card):
                check_playability[type(card)](i)

        # for each card in the board, check valid actions
        for offset, lane_id in zip((0, 3), (0, 1)):
            for i, creature in enumerate(cp.lanes[lane_id]):
                i += offset

                if creature.able_to_attack():
                    guards = []

                    for j, enemy_creature in enumerate(op.lanes[lane_id]):
                        if enemy_creature.has_ability('G'):
                            guards.append(j)

                    if guards:
                        for j in guards:
                            action_mask[121 + i * 4 + 1 + j] = 1
                    else:
                        action_mask[121 + i * 4] = 1

                        for j in range(len(op.lanes[lane_id])):
                            action_mask[121 + i * 4 + 1 + j] = 1

        if not self.items:
            action_mask = action_mask[:17] + action_mask[-24:]

        self.__action_mask = action_mask

        return self.__action_mask

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)

        return [seed]

    def act(self, action: Action):
        self.was_last_action_invalid = False

        if self.phase == Phase.DRAFT:
            self._act_on_draft(action)

            self._next_turn()

            if self.phase == Phase.DRAFT:
                self._new_draft_turn()
            elif self.phase == Phase.BATTLE:
                self._prepare_for_battle()

                self._new_battle_turn()

        elif self.phase == Phase.BATTLE:
            self._act_on_battle(action)

            if action.type == ActionType.PASS:
                self._next_turn()

                self._new_battle_turn()

        self.__available_actions = None
        self.__action_mask = None

    def _next_instance_id(self):
        self.instance_counter += 1

        return self.instance_counter

    def _new_draft(self) -> List[List[Card]]:
        cards = list(_cards)

        if not self.items:
            cards = list(filter(is_it(Creature), cards))

        self.np_random.shuffle(cards)

        pool = cards[:60]
        draft = []

        for _ in range(30):
            self.np_random.shuffle(pool)

            draft.append(pool[:3])

        return draft

    def _prepare_for_battle(self):
        """Prepare all game components for a battle phase"""
        for player in self.players:
            player.hand = []
            player.lanes = ([], [])

            self.np_random.shuffle(player.deck)

        d1, d2 = [], []

        for card1, card2 in zip(*(p.deck for p in self.players)):
            d1.append(card1.make_copy(self._next_instance_id()))
            d2.append(card2.make_copy(self._next_instance_id()))

        self.players[0].deck = list(reversed(d1))
        self.players[1].deck = list(reversed(d2))

        for player in self.players:
            player.draw(4)
            player.base_mana = 0

        second_player = self.players[PlayerOrder.SECOND]
        second_player.draw()
        second_player.bonus_mana = 1

    def _next_turn(self) -> bool:
        if self._current_player == PlayerOrder.FIRST:
            self._current_player = PlayerOrder.SECOND

            return False
        else:
            self._current_player = PlayerOrder.FIRST
            self.turn += 1

            if self.turn > 30 and self.phase == Phase.DRAFT:
                self.phase = Phase.BATTLE
                self.turn = 1

            return True

    def _new_draft_turn(self):
        """Initialize a draft turn"""
        current_draft_choices = self._draft_cards[self.turn - 1]

        for player in self.players:
            player.hand = current_draft_choices

    def _new_battle_turn(self):
        """Initialize a battle turn"""
        current_player = self.current_player

        for creature in current_player.lanes[Lane.LEFT]:
            creature.can_attack = True
            creature.has_attacked_this_turn = False

        for creature in current_player.lanes[Lane.RIGHT]:
            creature.can_attack = True
            creature.has_attacked_this_turn = False

        if current_player.base_mana > 0 and current_player.mana == 0:
            current_player.bonus_mana = 0

        if current_player.base_mana < 12:
            current_player.base_mana += 1

        current_player.mana = current_player.base_mana \
            + current_player.bonus_mana

        amount_in_hand = len(current_player.hand)
        amount_to_draw = 1 + current_player.bonus_draw

        if self.turn > 50:
            current_player.deck = []

        try:
            current_player.draw(amount_to_draw)
        except FullHandError:
            pass
        except EmptyDeckError:
            deck_burn = current_player.health - current_player.next_rune
            current_player.damage(deck_burn)

        current_player.bonus_draw = 0
        current_player.last_drawn = len(current_player.hand) - amount_in_hand

    def _find_card(self, instance_id: int) -> Card:
        c, o = self.current_player, self.opposing_player

        location_mapping = {
            Location.PLAYER_HAND: c.hand,
            Location.ENEMY_HAND: o.hand,
            Location.PLAYER_LEFT_LANE: c.lanes[0],
            Location.PLAYER_RIGHT_LANE: c.lanes[1],
            Location.ENEMY_LEFT_LANE: o.lanes[0],
            Location.ENEMY_RIGHT_LANE: o.lanes[1]
        }

        for location, cards in location_mapping.items():
            for card in cards:
                if card.instance_id == instance_id:
                    return card

        raise InvalidCardError(instance_id)

    def _act_on_draft(self, action: Action):
        """Execute the action intended by the player in this draft turn"""
        chosen_index = action.origin if action.origin is not None else 0
        card = self.current_player.hand[chosen_index]

        self.current_player.deck.append(card)

    def _act_on_battle(self, action: Action):
        """Execute the actions intended by the player in this battle turn"""
        try:
            origin, target = action.origin, action.target

            if isinstance(action.origin, int):
                origin = self._find_card(origin)

            if action.type == ActionType.SUMMON:
                if isinstance(action.target, int):
                    target = Lane(target)

                self._do_summon(origin, target)
            elif action.type == ActionType.ATTACK:
                if isinstance(action.target, int):
                    target = self._find_card(target)

                self._do_attack(origin, target)
            elif action.type == ActionType.USE:
                if isinstance(action.target, int):
                    target = self._find_card(target)

                self._do_use(origin, target)
            elif action.type == ActionType.PASS:
                pass
            else:
                raise MalformedActionError("Invalid action type")

            action.resolved_origin = origin
            action.resolved_target = target

            self.current_player.actions.append(action)
        except (NotEnoughManaError, MalformedActionError,
                FullLaneError, InvalidCardError):
            self.was_last_action_invalid = True

        for player in self.players:
            for lane in player.lanes:
                for creature in lane:
                    if creature.is_dead:
                        lane.remove(creature)

        if self.players[PlayerOrder.FIRST].health <= 0:
            self.phase = Phase.ENDED
            self.winner = PlayerOrder.SECOND
        elif self.players[PlayerOrder.SECOND].health <= 0:
            self.phase = Phase.ENDED
            self.winner = PlayerOrder.FIRST

    def _do_summon(self, origin, target):
        current_player = self.current_player
        opposing_player = self.opposing_player

        if origin.cost > current_player.mana:
            raise NotEnoughManaError()

        if not isinstance(origin, Creature):
            raise MalformedActionError("Card being summoned is not a "
                                       "creature")

        if not isinstance(target, Lane):
            raise MalformedActionError("Target is not a lane")

        if len(current_player.lanes[target]) >= 3:
            raise FullLaneError()

        try:
            current_player.hand.remove(origin)
        except ValueError:
            raise MalformedActionError("Card is not in player's hand")

        origin.can_attack = False

        current_player.lanes[target].append(origin)

        current_player.bonus_draw += origin.card_draw
        current_player.health += origin.player_hp
        opposing_player.health += origin.enemy_hp

        current_player.mana -= origin.cost

    def _do_attack(self, origin, target):
        current_player = self.current_player
        opposing_player = self.opposing_player

        if not isinstance(origin, Creature):
            raise MalformedActionError("Attacking card is not a "
                                       "creature")

        if origin in current_player.lanes[Lane.LEFT]:
            origin_lane = Lane.LEFT
        elif origin in current_player.lanes[Lane.RIGHT]:
            origin_lane = Lane.RIGHT
        else:
            raise MalformedActionError("Attacking creature is not "
                                       "owned by player")

        guard_creatures = []

        for creature in opposing_player.lanes[origin_lane]:
            if creature.has_ability('G'):
                guard_creatures.append(creature)

        if len(guard_creatures) > 0:
            valid_targets = guard_creatures
        else:
            valid_targets = [None] + opposing_player.lanes[origin_lane]

        if target not in valid_targets:
            raise MalformedActionError("Invalid target")

        if not origin.able_to_attack():
            raise MalformedActionError("Attacking creature cannot "
                                       "attack")

        if target is None:
            damage_dealt = opposing_player.damage(origin.attack)

        elif isinstance(target, Creature):
            target_defense = target.defense

            try:
                damage_dealt = target.damage(
                    origin.attack,
                    lethal=origin.has_ability('L'))
            except WardShieldError:
                damage_dealt = 0

            try:
                origin.damage(
                    target.attack,
                    lethal=target.has_ability('L'))
            except WardShieldError:
                damage_dealt = 0

            excess_damage = damage_dealt - target_defense

            if 'B' in origin.keywords and excess_damage > 0:
                opposing_player.damage(excess_damage)
        else:
            raise MalformedActionError("Target is not a creature or "
                                       "a player")

        if 'D' in origin.keywords:
            current_player.health += damage_dealt

        origin.has_attacked_this_turn = True

    def _do_use(self, origin, target):
        current_player = self.current_player
        opposing_player = self.opposing_player

        if origin.cost > current_player.mana:
            raise NotEnoughManaError()

        if target is not None and \
                not isinstance(target, Creature):
            error = "Target is not a creature or a player"
            raise MalformedActionError(error)

        try:
            current_player.hand.remove(origin)
        except ValueError:
            raise MalformedActionError("Card is not in player's hand")

        if isinstance(origin, GreenItem):
            is_own_creature = \
                target in current_player.lanes[Lane.LEFT] or \
                target in current_player.lanes[Lane.RIGHT]

            if target is None or not is_own_creature:
                error = "Green items should be used on friendly " \
                        "creatures"
                raise MalformedActionError(error)

            target.attack += origin.attack
            target.defense += origin.defense
            target.keywords = target.keywords.union(origin.keywords)

            if target.defense <= 0:
                target.is_dead = True

            current_player.bonus_draw += origin.card_draw
            current_player.health += origin.player_hp
            opposing_player.health += origin.enemy_hp

        elif isinstance(origin, RedItem):
            is_opp_creature = \
                target in opposing_player.lanes[Lane.LEFT] or \
                target in opposing_player.lanes[Lane.RIGHT]

            if target is None or not is_opp_creature:
                error = "Red items should be used on enemy " \
                        "creatures"
                raise MalformedActionError(error)

            target.attack += origin.attack
            target.keywords = target.keywords.difference(origin.keywords)

            try:
                target.damage(-origin.defense)
            except WardShieldError:
                pass

            if target.defense <= 0:
                target.is_dead = True

            current_player.bonus_draw += origin.card_draw
            current_player.health += origin.player_hp
            opposing_player.health += origin.enemy_hp

        elif isinstance(origin, BlueItem):
            is_opp_creature = \
                target in opposing_player.lanes[Lane.LEFT] or \
                target in opposing_player.lanes[Lane.RIGHT]

            if target is not None and not is_opp_creature:
                error = "Blue items should be used on enemy " \
                        "creatures or enemy player"
                raise MalformedActionError(error)

            if isinstance(target, Creature):
                target.attack += origin.attack
                target.keywords = target.keywords.difference(origin.keywords)

                try:
                    target.damage(-origin.defense)
                except WardShieldError:
                    pass

                if target.defense <= 0:
                    target.is_dead = True

            elif target is None:
                opposing_player.damage(-origin.defense)
            else:
                raise MalformedActionError("Invalid target")

            current_player.bonus_draw += origin.card_draw
            current_player.health += origin.player_hp
            opposing_player.health += origin.enemy_hp

        else:
            error = "Card being used is not an item"
            raise MalformedActionError(error)

        current_player.mana -= origin.cost

    def clone(self) -> 'State':
        cloned_state = State.empty_copy()

        cloned_state.np_random = np.random.RandomState()
        cloned_state.np_random.set_state(self.np_random.get_state())

        cloned_state.phase = self.phase
        cloned_state.turn = self.turn
        cloned_state._current_player = self._current_player
        cloned_state.__available_actions = self.__available_actions
        cloned_state.winner = self.winner
        cloned_state._draft_cards = self._draft_cards
        cloned_state.players = tuple([player.clone() for player in self.players])

        return cloned_state

        # return pickle.loads(pickle.dumps(self, -1))

    def __str__(self) -> str:
        encoding = ""

        p, o = self.current_player, self.opposing_player

        for cp in p, o:
            draw = cp.last_drawn if cp == self.current_player else 1 + cp.bonus_draw

            encoding += f"{cp.health} {cp.base_mana + cp.bonus_mana} " \
                f"{len(cp.deck)} {cp.next_rune} {draw}\n"

        op_hand = len(o.hand) if self.phase != Phase.DRAFT else 0
        last_actions = []

        for action in reversed(o.actions[:-1]):
            if action.type == ActionType.PASS:
                break

            last_actions.append(action)

        encoding += f"{op_hand} {len(last_actions)}\n"

        for a in reversed(last_actions):
            target_id = -1 if a.target is None else a.target

            encoding += f"{a.resolved_origin.id} {a.type.name} " \
                f"{a.origin} {target_id}\n"

        cards = p.hand + p.lanes[0] + p.lanes[1] + o.lanes[0] + o.lanes[1]

        encoding += f"{len(cards)}\n"

        for c in cards:
            if c in p.hand:
                c.location = 0
                c.lane = -1
            elif c in p.lanes[0] + p.lanes[1]:
                c.location = 1
                c.lane = 0 if c in p.lanes[0] else 1
            elif c in o.lanes[0] + o.lanes[1]:
                c.location = -1
                c.lane = 0 if c in o.lanes[0] else 1

            if isinstance(c.type, int):
                c.cardType = c.type
            elif c.type == 'creature':
                c.cardType = 0
            elif c.type == 'itemGreen':
                c.cardType = 1
            elif c.type == 'itemRed':
                c.cardType = 2
            elif c.type == 'itemBlue':
                c.cardType = 3

            abilities = list('------')

            for i, a in enumerate(list('BCDGLW')):
                if c.has_ability(a):
                    abilities[i] = a

            c.abilities = "".join(abilities)

            c.instance_id = -1 if c.instance_id is None else c.instance_id

        for i, c in enumerate(cards):
            encoding += f"{c.id} {c.instance_id} {c.location} {c.cardType} " \
                f"{c.cost} {c.attack} {c.defense} {c.abilities} " \
                f"{c.player_hp} {c.enemy_hp} {c.card_draw} {c.lane} \n"

        return encoding

    def can_play(self, card):
        p, op = self.current_player, self.opposing_player

        if card.cost > p.mana:
            return False

        if isinstance(card, Creature):
            return sum(map(len, p.lanes)) < 6
        elif isinstance(card, GreenItem):
            return sum(map(len, p.lanes)) > 0
        elif isinstance(card, RedItem):
            return sum(map(len, op.lanes)) > 0
        else:
            return True

    def is_draft(self):
        return self.phase == Phase.DRAFT

    def is_battle(self):
        return self.phase == Phase.BATTLE

    def is_ended(self):
        return self.phase == Phase.ENDED

    @staticmethod
    def empty_copy():
        class Empty(State):
            def __init__(self):
                pass

        new_copy = Empty()
        new_copy.__class__ = State

        return new_copy


Game = State
