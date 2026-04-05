#!/usr/bin/env python3
"""
Snake bot with:
1) parser utility for incoming game JSON
2) strict collision avoidance (boundary, walls, snakes)
3) poison-apple avoidance unless it is absolutely necessary
"""

import json
import sys
from collections import deque

APPLE_BASE_LIFE = {
    "NORMAL": 40,
    "GOD": 30,
    "SPEED": 30,
    "SLEEP": 30,
    "POISON": 40,
}

APPLE_TRACKER = {}
MOVES = ["UP", "DOWN", "LEFT", "RIGHT"]
APPLE_PRIORITY = {
    "GOD": 18,
    "SPEED": -35,
    "SLEEP": 18,
    "NORMAL": 12,
    "POISON": -40,
}
DEFAULT_ENERGY = 100
CRITICAL_ENERGY = 20
HUNGER_RISKY_ENERGY = 35

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


def _to_coord_set(items):
    return {(p["x"], p["y"]) for p in items}


def next_position(head, move):
    return {
        "UP": {"x": head["x"], "y": head["y"] - 1},
        "DOWN": {"x": head["x"], "y": head["y"] + 1},
        "LEFT": {"x": head["x"] - 1, "y": head["y"]},
        "RIGHT": {"x": head["x"] + 1, "y": head["y"]},
    }[move]


def parse_incoming_state(raw_state, apple_tracker=None, apple_base_life=None):
    """Parse incoming JSON/dict and return the 5 requested structures.

    Returns:
      walls_with_boundary (set[(x, y)])
      trees (set[(x, y)])
      opponent_snake (list[(x, y)])
      apples_dict (dict[(x, y)] -> {type, spawn_turn, original_life, remaining_life})
      my_snake (list[(x, y)])
    """
    game_state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
    tracker = APPLE_TRACKER if apple_tracker is None else apple_tracker
    life_table = APPLE_BASE_LIFE if apple_base_life is None else apple_base_life

    grid_width = game_state.get("grid_width", 0)
    grid_height = game_state.get("grid_height", 0)
    turn = game_state.get("turn", 0)

    map_data = game_state.get("map", {}) or {}
    wall_cells = _to_coord_set(map_data.get("obstacles", []))
    trees = _to_coord_set(map_data.get("trees", []))

    outer_boundary = set()
    for x in range(-1, grid_width + 1):
        outer_boundary.add((x, -1))
        outer_boundary.add((x, grid_height))
    for y in range(0, grid_height):
        outer_boundary.add((-1, y))
        outer_boundary.add((grid_width, y))

    walls_with_boundary = wall_cells | outer_boundary

    snakes = game_state.get("snakes", [])
    my_snake = [(p["x"], p["y"]) for p in snakes[0].get("body", [])] if snakes else []
    opponent_snake = [(p["x"], p["y"]) for p in snakes[1].get("body", [])] if len(snakes) > 1 else []

    active_positions = set()
    for apple in game_state.get("apples", []):
        pos = (apple["x"], apple["y"])
        active_positions.add(pos)

        apple_type = apple.get("type", "NORMAL")
        base_life = life_table.get(apple_type, 40)

        if pos not in tracker:
            tracker[pos] = {
                "type": apple_type,
                "spawn_turn": apple.get("spawned_at", turn),
                "original_life": base_life,
                "remaining_life": base_life,
            }

        tracker[pos]["type"] = apple_type
        tracker[pos]["original_life"] = base_life

        spawn_turn = tracker[pos].get("spawn_turn", turn)
        if "spawned_at" in apple:
            spawn_turn = apple["spawned_at"]
            tracker[pos]["spawn_turn"] = spawn_turn

        age = max(0, turn - spawn_turn)
        tracker[pos]["remaining_life"] = max(0, base_life - age)

    stale = [pos for pos in tracker if pos not in active_positions]
    for pos in stale:
        del tracker[pos]

    apples_dict = {pos: data.copy() for pos, data in tracker.items()}

    return walls_with_boundary, trees, opponent_snake, apples_dict, my_snake


def get_forbidden_cells(game_state):
    """Cells we should not step into: walls, trees, and all snake bodies."""
    forbidden = set()

    map_data = game_state.get("map", {}) or {}
    for obs in map_data.get("obstacles", []):
        forbidden.add((obs["x"], obs["y"]))

    for tree in map_data.get("trees", []):
        forbidden.add((tree["x"], tree["y"]))

    for snake in game_state.get("snakes", []):
        for cell in snake.get("body", []):
            forbidden.add((cell["x"], cell["y"]))

    return forbidden


def get_safe_moves(head, grid_width, grid_height, forbidden_cells):
    safe = []
    for move in MOVES:
        nxt = next_position(head, move)
        coord = (nxt["x"], nxt["y"])
        in_bounds = 0 <= nxt["x"] < grid_width and 0 <= nxt["y"] < grid_height
        if in_bounds and coord not in forbidden_cells:
            safe.append(move)
    return safe


def flood_fill_space(start, grid_width, grid_height, blocked_cells, limit=120):
    """Estimate how much free space is reachable from a position."""
    visited = {start}
    queue = deque([start])
    space = 0

    while queue and space < limit:
        current = queue.popleft()
        space += 1
        for move in MOVES:
            nxt = next_position({"x": current[0], "y": current[1]}, move)
            coord = (nxt["x"], nxt["y"])
            if coord in visited:
                continue
            if not (0 <= nxt["x"] < grid_width and 0 <= nxt["y"] < grid_height):
                continue
            if coord in blocked_cells:
                continue
            visited.add(coord)
            queue.append(coord)

    return space


def count_open_neighbors(pos, grid_width, grid_height, blocked_cells):
    open_neighbors = 0
    for move in MOVES:
        nxt = next_position({"x": pos[0], "y": pos[1]}, move)
        coord = (nxt["x"], nxt["y"])
        if 0 <= nxt["x"] < grid_width and 0 <= nxt["y"] < grid_height and coord not in blocked_cells:
            open_neighbors += 1
    return open_neighbors


def get_opponent_threat_cells(opponent_head, grid_width, grid_height, forbidden_cells):
    """Cells the opponent head can contest next turn."""
    if not opponent_head:
        return set()

    threat_cells = set()
    for move in MOVES:
        nxt = next_position(opponent_head, move)
        coord = (nxt["x"], nxt["y"])
        if not (0 <= nxt["x"] < grid_width and 0 <= nxt["y"] < grid_height):
            continue
        if coord in forbidden_cells:
            continue
        threat_cells.add(coord)
    return threat_cells


def is_future_trap_position(reachable_space, open_neighbors, my_length, speed_active):
    escape_room_needed = my_length + (6 if speed_active else 4)
    if open_neighbors <= 0:
        return True
    if reachable_space < my_length:
        return True
    if reachable_space < escape_room_needed and open_neighbors <= 1:
        return True
    return False


def shortest_path_distance(start, targets, grid_width, grid_height, blocked_cells, limit=140):
    """Shortest grid distance to any target using blocked-cell aware BFS."""
    if not targets:
        return None
    if start in targets:
        return 0

    visited = {start}
    queue = deque([(start, 0)])

    while queue:
        current, dist = queue.popleft()
        if dist >= limit:
            continue

        for move in MOVES:
            nxt = next_position({"x": current[0], "y": current[1]}, move)
            coord = (nxt["x"], nxt["y"])
            if coord in visited:
                continue
            if not (0 <= nxt["x"] < grid_width and 0 <= nxt["y"] < grid_height):
                continue
            if coord in blocked_cells:
                continue
            if coord in targets:
                return dist + 1
            visited.add(coord)
            queue.append((coord, dist + 1))

    return None


def choose_survival_food_target(head, apples, grid_width, grid_height, blocked_cells):
    """Pick the edible apple with the most reachable path under current obstacles."""
    if not apples:
        return None, None

    head_pos = (head["x"], head["y"])
    best_apple = None
    best_distance = None

    for apple in apples:
        apple_pos = (apple["x"], apple["y"])
        path_distance = shortest_path_distance(
            head_pos,
            {apple_pos},
            grid_width,
            grid_height,
            blocked_cells,
            limit=140,
        )
        if path_distance is None:
            path_distance = calculate_path_distance(head_pos, apple_pos)

        if best_distance is None or path_distance < best_distance:
            best_distance = path_distance
            best_apple = apple

    return best_apple, best_distance


def get_hunger_pressure(my_snake):
    """Return (energy, hunger_pressure) where pressure is in [0.0, 1.0]."""
    energy = my_snake.get("energy", DEFAULT_ENERGY)
    if energy <= 10:
        return energy, 1.0
    if energy <= 20:
        return energy, 0.95
    if energy <= 28:
        return energy, 0.75
    if energy <= 45:
        return energy, 0.4
    return energy, 0.0


def is_hunger_critical(my_snake):
    return my_snake.get("energy", DEFAULT_ENERGY) <= CRITICAL_ENERGY


def is_hunger_risky(my_snake):
    return my_snake.get("energy", DEFAULT_ENERGY) <= HUNGER_RISKY_ENERGY


def should_avoid_growth(my_snake_state, opponent_snake_state, lead_margin=5):
    my_length = my_snake_state.get("length", len(my_snake_state.get("body", [])))
    opponent_length = opponent_snake_state.get("length", len(opponent_snake_state.get("body", [])))
    return my_length > (opponent_length + lead_margin)


def is_speed_active(my_snake):
    return my_snake.get("speed_turns", 0) > 0


def score_apple(head, apple, apples_dict, hunger_pressure=0.0, speed_active=False):
    pos = (apple["x"], apple["y"])
    apple_meta = apples_dict.get(pos, {})
    apple_type = apple.get("type", "NORMAL")
    remaining_life = apple_meta.get("remaining_life", 10**9)
    distance = abs(head["x"] - apple["x"]) + abs(head["y"] - apple["y"])
    score = APPLE_PRIORITY.get(apple_type, 0) + max(0, remaining_life - distance)

    if apple_type == "SPEED":
        score -= 60 if not speed_active else 20
    elif apple_type == "GOD":
        score -= 8 if speed_active else 0

    if apple_type != "POISON":
        score += max(0, 14 - distance) * (0.3 + 1.4 * hunger_pressure)
        if hunger_pressure >= 0.95:
            score += 60

    return score


def score_move(
    head,
    move,
    game_state,
    forbidden_cells,
    apples_dict,
    poison_positions,
    growth_apple_positions=None,
    avoid_growth=False,
    hunger_critical=False,
):
    grid_width = game_state["grid_width"]
    grid_height = game_state["grid_height"]
    nxt = next_position(head, move)
    coord = (nxt["x"], nxt["y"])
    my_snake = game_state["snakes"][0]
    my_length = max(1, my_snake.get("length", len(my_snake.get("body", [])) or 1))
    my_energy, hunger_pressure = get_hunger_pressure(my_snake)
    speed_active = is_speed_active(my_snake)
    growth_apple_positions = growth_apple_positions or set()

    score = 0.0

    # Step 1: always prefer moves that preserve maximum room to maneuver.
    reachable_space = flood_fill_space(coord, grid_width, grid_height, forbidden_cells)
    score += min(reachable_space, 120) * 1.5

    open_neighbors = count_open_neighbors(coord, grid_width, grid_height, forbidden_cells)
    score += open_neighbors * 8

    trap_penalty_scale = 1.0 - (0.45 * hunger_pressure)
    if speed_active:
        trap_penalty_scale += 0.45
    if open_neighbors <= 1:
        if reachable_space <= max(6, my_length + 1):
            score -= 45 * trap_penalty_scale
        else:
            score -= 12 * trap_penalty_scale
    if reachable_space <= max(4, my_length // 2):
        score -= 70 * trap_penalty_scale
    elif reachable_space <= max(8, my_length + 2):
        score -= 26 * trap_penalty_scale

    if is_future_trap_position(reachable_space, open_neighbors, my_length, speed_active):
        score -= 1200 * trap_penalty_scale

    if coord in poison_positions:
        score -= 85 - (20 * hunger_pressure)

    if avoid_growth and not hunger_critical and coord in growth_apple_positions:
        score -= 350

    if speed_active:
        # While speed is active, prefer much wider lanes so the doubled movement stays safe.
        if reachable_space <= max(10, my_length + 4):
            score -= 28 * trap_penalty_scale
        if open_neighbors <= 2:
            score -= 18 * trap_penalty_scale

    # Step 3: stay away from opponent heads and their immediate threat zone.
    snakes = game_state.get("snakes", [])
    if len(snakes) > 1 and snakes[1].get("body"):
        opp_head = snakes[1]["body"][0]
        opp_dist = abs(coord[0] - opp_head["x"]) + abs(coord[1] - opp_head["y"])
        if opp_dist == 1:
            score -= 60
        elif opp_dist == 2:
            score -= 20
        else:
            score += min(opp_dist, 12)

    # Step 2 and Step 5: move toward valuable apples if they are actually reachable.
    if apples_dict:
        best_apple_score = None
        best_apple_distance = None
        for apple_pos, apple_meta in apples_dict.items():
            apple = {"x": apple_pos[0], "y": apple_pos[1], "type": apple_meta.get("type", "NORMAL")}
            apple_value = score_apple(head, apple, apples_dict, hunger_pressure, speed_active)
            distance = abs(coord[0] - apple_pos[0]) + abs(coord[1] - apple_pos[1])
            candidate_score = apple_value - distance * 2
            if best_apple_score is None or candidate_score > best_apple_score:
                best_apple_score = candidate_score
                best_apple_distance = distance

        if best_apple_score is not None:
            score += best_apple_score * 0.6
            score += max(0, 18 - best_apple_distance) * 2

        edible_targets = {
            pos for pos, meta in apples_dict.items() if meta.get("type", "NORMAL") != "POISON"
        }
        if not edible_targets:
            edible_targets = set(apples_dict.keys())

        dist_to_edible = shortest_path_distance(
            coord,
            edible_targets,
            grid_width,
            grid_height,
            forbidden_cells,
            limit=120,
        )

        if dist_to_edible is not None:
            score += max(0, 20 - dist_to_edible) * (1.5 + 6 * hunger_pressure)
            # Emergency hunger mode: strongly bias moves that can reach food in time.
            if my_energy <= dist_to_edible + 6:
                score += 120
            elif my_energy <= dist_to_edible + 10:
                score += 45

            if my_energy <= CRITICAL_ENERGY:
                score += max(0, 90 - dist_to_edible * 12)
                score += max(0, 18 - reachable_space) * 2

    return score


def sanitize_move(head, move, grid_width, grid_height, forbidden_cells):
    """Guarantee returned move stays in bounds and avoids blocked cells."""
    if move in MOVES:
        nxt = next_position(head, move)
        coord = (nxt["x"], nxt["y"])
        if 0 <= nxt["x"] < grid_width and 0 <= nxt["y"] < grid_height and coord not in forbidden_cells:
            return move

    for fallback in MOVES:
        nxt = next_position(head, fallback)
        coord = (nxt["x"], nxt["y"])
        if 0 <= nxt["x"] < grid_width and 0 <= nxt["y"] < grid_height and coord not in forbidden_cells:
            return fallback

    return None


def choose_priority_apple(head, apples, apples_dict, hunger_pressure, energy, speed_active):
    """Select an apple balancing type value, expiry, distance, and hunger urgency."""
    if not apples:
        return None

    def apple_score(apple):
        pos = (apple["x"], apple["y"])
        apple_meta = apples_dict.get(pos, {})
        remaining_life = apple_meta.get("remaining_life", 10**9)
        distance = abs(head["x"] - apple["x"]) + abs(head["y"] - apple["y"])
        apple_type = apple.get("type", "NORMAL")
        value = APPLE_PRIORITY.get(apple_type, 0)

        score = value * 2.0
        score += max(0, remaining_life - distance)
        score -= distance * 2.3

        if apple_type == "SPEED":
            score -= 80 if not (hunger_pressure >= 0.75 and energy <= distance + 6) else 15
        elif apple_type == "GOD":
            score -= 12 if speed_active else 0

        # Hunger urgency: prefer closer edible apples before energy gets critical.
        if apple_type != "POISON":
            score += max(0, 18 - distance) * (0.5 + 2.8 * hunger_pressure)
            if energy <= distance + 6:
                score += 120

        return score

    return max(apples, key=apple_score)


def get_move_towards(head, target):
    dx = target["x"] - head["x"]
    dy = target["y"] - head["y"]
    if abs(dx) > abs(dy):
        return "RIGHT" if dx > 0 else "LEFT"
    return "DOWN" if dy > 0 else "UP"


def should_allow_poison(my_snake, safe_moves, head, poison_positions):
    """Poison is allowed only if every safe move lands on poison."""
    if not safe_moves:
        return False

    non_poison_safe_exists = False
    for move in safe_moves:
        nxt = next_position(head, move)
        if (nxt["x"], nxt["y"]) not in poison_positions:
            non_poison_safe_exists = True
            break

    if non_poison_safe_exists:
        return False

    # Very required: only poison-safe moves remain.
    _ = my_snake
    return True


def rank_safe_moves(
    game_state,
    head,
    safe_moves,
    forbidden,
    apples_dict,
    poison_positions,
    growth_apple_positions=None,
    avoid_growth=False,
    hunger_critical=False,
):
    if not safe_moves:
        return []

    ranked_moves = []
    for move in safe_moves:
        ranked_moves.append(
            (
                score_move(
                    head,
                    move,
                    game_state,
                    forbidden,
                    apples_dict,
                    poison_positions,
                    growth_apple_positions,
                    avoid_growth,
                    hunger_critical,
                ),
                move,
            )
        )

    ranked_moves.sort(reverse=True)
    return ranked_moves


def detect_opponent_target_apple(opponent_head, apples, apples_dict):
    if not apples:
        return None

    best_apple = None
    best_score = float("-inf")
    opponent_pos = (opponent_head["x"], opponent_head["y"])

    for apple in apples:
        apple_pos = (apple["x"], apple["y"])
        apple_meta = apples_dict.get(apple_pos, {})
        remaining_life = apple_meta.get("remaining_life", 10**9)
        priority = APPLE_PRIORITY.get(apple.get("type", "NORMAL"), 0)
        distance = calculate_path_distance(opponent_pos, apple_pos)
        score = priority + max(0, remaining_life - distance)

        if score > best_score:
            best_score = score
            best_apple = apple

    return best_apple


def calculate_path_distance(pos1, pos2):
    return abs(pos1[0] - pos2[0]) + abs(pos1[1] - pos2[1])


def can_intercept_apple(my_head, opponent_head, target_apple, my_snake_length):
    if not target_apple:
        return False

    my_pos = (my_head["x"], my_head["y"])
    opponent_pos = (opponent_head["x"], opponent_head["y"])
    apple_pos = (target_apple["x"], target_apple["y"])

    my_distance = calculate_path_distance(my_pos, apple_pos)
    opponent_distance = calculate_path_distance(opponent_pos, apple_pos)
    return my_distance <= opponent_distance + 1 and my_snake_length > 5


def find_optimal_cutoff_positions(my_head, opponent_head, target_apple, grid_width, grid_height, forbidden):
    if not target_apple:
        return []

    candidates = []
    opponent_x = opponent_head["x"]
    opponent_y = opponent_head["y"]
    apple_pos = (target_apple["x"], target_apple["y"])
    my_pos = (my_head["x"], my_head["y"])

    for offset_x in (-1, 0, 1):
        for offset_y in (-1, 0, 1):
            if offset_x == 0 and offset_y == 0:
                continue

            pos = (opponent_x + offset_x, opponent_y + offset_y)
            if not (0 <= pos[0] < grid_width and 0 <= pos[1] < grid_height):
                continue
            if pos in forbidden:
                continue

            distance_from_my_head = calculate_path_distance(my_pos, pos)
            distance_to_apple = calculate_path_distance(pos, apple_pos)
            if distance_from_my_head < 15 and distance_to_apple < 10:
                candidates.append((pos, distance_to_apple, distance_from_my_head))

    candidates.sort(key=lambda item: (item[1], item[2]))
    return [pos for pos, _, _ in candidates[:5]]


def has_sufficient_body_length(my_snake, required_blocks):
    return len(my_snake) > (required_blocks + 3)


def calculate_shedding_positions(my_head, opponent_head, target_apple, my_snake, game_state, forbidden):
    if not target_apple:
        return []

    grid_width = game_state.get("grid_width", 0)
    grid_height = game_state.get("grid_height", 0)
    opponent_pos = (opponent_head["x"], opponent_head["y"])
    apple_pos = (target_apple["x"], target_apple["y"])
    my_pos = (my_head["x"], my_head["y"])
    my_body = set(my_snake)
    direct_distance = calculate_path_distance(opponent_pos, apple_pos)
    candidates = []

    for x in range(opponent_pos[0] - 3, opponent_pos[0] + 4):
        for y in range(opponent_pos[1] - 3, opponent_pos[1] + 4):
            pos = (x, y)
            if not (0 <= x < grid_width and 0 <= y < grid_height):
                continue
            if pos in forbidden or pos in my_body:
                continue

            via_distance = calculate_path_distance(opponent_pos, pos) + calculate_path_distance(pos, apple_pos)
            if via_distance <= direct_distance:
                continue

            distance_from_my_head = calculate_path_distance(my_pos, pos)
            candidates.append((pos, distance_from_my_head))

    candidates.sort(key=lambda item: item[1])
    return [pos for pos, _ in candidates[:4]]


def is_position_safe_for_shedding(shed_position, my_head, grid_width, grid_height, forbidden, my_snake):
    if not my_snake:
        return False

    test_snake = list(my_snake[:-1]) if len(my_snake) > 1 else list(my_snake)
    test_forbidden = set(forbidden)
    test_forbidden.update(test_snake)
    test_forbidden.add(shed_position)

    reachable_space = flood_fill_space(my_head, grid_width, grid_height, test_forbidden)
    return reachable_space > 8


def find_walls_to_extend(my_head, forbidden_cells, game_state):
    grid_width = game_state.get("grid_width", 0)
    grid_height = game_state.get("grid_height", 0)
    my_pos = (my_head["x"], my_head["y"])
    candidates = []

    for x in range(my_pos[0] - 4, my_pos[0] + 5):
        for y in range(my_pos[1] - 4, my_pos[1] + 5):
            pos = (x, y)
            if not (0 <= x < grid_width and 0 <= y < grid_height):
                continue
            if pos not in forbidden_cells:
                continue

            wall_neighbors = 0
            for delta_x in (-1, 0, 1):
                for delta_y in (-1, 0, 1):
                    if delta_x == 0 and delta_y == 0:
                        continue
                    neighbor = (x + delta_x, y + delta_y)
                    if neighbor in forbidden_cells:
                        wall_neighbors += 1

            if wall_neighbors >= 2:
                distance = calculate_path_distance(my_pos, pos)
                candidates.append((pos, wall_neighbors, distance))

    candidates.sort(key=lambda item: (-item[1], item[2]))
    return [pos for pos, _, _ in candidates[:3]]


def calculate_blocking_pattern(my_head, opponent_pos, target_apple, my_snake, game_state, forbidden):
    grid_width = game_state.get("grid_width", 0)
    grid_height = game_state.get("grid_height", 0)
    opponent_x, opponent_y = opponent_pos
    apple_pos = (target_apple["x"], target_apple["y"])
    my_body = set(my_snake)
    candidates = []

    horizontal_blocking = abs(apple_pos[0] - opponent_x) > abs(apple_pos[1] - opponent_y)
    offsets = (-2, -1, 1, 2)

    if horizontal_blocking:
        for offset in offsets:
            pos = (opponent_x, opponent_y + offset)
            if not (0 <= pos[0] < grid_width and 0 <= pos[1] < grid_height):
                continue
            if pos in forbidden or pos in my_body:
                continue
            candidates.append(pos)
    else:
        for offset in offsets:
            pos = (opponent_x + offset, opponent_y)
            if not (0 <= pos[0] < grid_width and 0 <= pos[1] < grid_height):
                continue
            if pos in forbidden or pos in my_body:
                continue
            candidates.append(pos)

    return candidates[:4]


def evaluate_block_safety(my_head, block_positions, game_state, forbidden, my_snake):
    if not block_positions:
        return False

    grid_width = game_state.get("grid_width", 0)
    grid_height = game_state.get("grid_height", 0)
    my_pos = (my_head["x"], my_head["y"])
    test_forbidden = set(forbidden)
    test_forbidden.update(block_positions)
    test_forbidden.update(my_snake)

    reachable_space = flood_fill_space(my_pos, grid_width, grid_height, test_forbidden)
    safe_open_neighbors = count_open_neighbors(my_pos, grid_width, grid_height, test_forbidden)
    return reachable_space > 12 and safe_open_neighbors >= 2


def decide_move(game_state):
    # Keep parser state fresh every turn for downstream strategy use.
    _, _, _, apples_dict, _ = parse_incoming_state(game_state)

    snakes = game_state.get("snakes", [])
    if not snakes:
        return "UP"

    my_snake = snakes[0]
    if not my_snake.get("alive", False):
        return my_snake.get("direction", "UP")
    opponent_snake = snakes[1] if len(snakes) > 1 else {}
    my_length = my_snake.get("length", len(my_snake.get("body", [])))
    opponent_length = opponent_snake.get("length", len(opponent_snake.get("body", [])))
    my_energy, hunger_pressure = get_hunger_pressure(my_snake)
    hunger_critical = is_hunger_critical(my_snake)
    hunger_risky = is_hunger_risky(my_snake)
    avoid_growth = should_avoid_growth(my_snake, opponent_snake)
    if hunger_risky:
        avoid_growth = False
    speed_active = is_speed_active(my_snake)

    head = my_snake["body"][0]
    grid_width = game_state["grid_width"]
    grid_height = game_state["grid_height"]

    forbidden = get_forbidden_cells(game_state)
    safe_moves = get_safe_moves(head, grid_width, grid_height, forbidden)

    survivable_moves = []
    for move in safe_moves:
        nxt = next_position(head, move)
        next_pos = (nxt["x"], nxt["y"])
        future_space = flood_fill_space(next_pos, grid_width, grid_height, forbidden)
        future_open = count_open_neighbors(next_pos, grid_width, grid_height, forbidden)
        if not is_future_trap_position(future_space, future_open, max(1, my_length), speed_active):
            survivable_moves.append(move)

    if survivable_moves:
        safe_moves = survivable_moves

    opponent_head = opponent_snake.get("body", [{}])[0] if opponent_snake.get("body") else None
    opponent_threat_cells = get_opponent_threat_cells(opponent_head, grid_width, grid_height, forbidden)
    if opponent_threat_cells and opponent_length >= my_length:
        safer_vs_head = []
        for move in safe_moves:
            nxt = next_position(head, move)
            if (nxt["x"], nxt["y"]) not in opponent_threat_cells:
                safer_vs_head.append(move)
        if safer_vs_head:
            safe_moves = safer_vs_head

    if not safe_moves:
        return my_snake.get("direction", "UP")

    apples = game_state.get("apples", [])
    if not apples:
        ranked = rank_safe_moves(
            game_state,
            head,
            safe_moves,
            forbidden,
            apples_dict,
            set(),
            set(),
            avoid_growth,
            hunger_critical,
        )
        best_move = ranked[0][1] if ranked else None
        return best_move or safe_moves[0]

    poison_positions = {
        (a["x"], a["y"]) for a in apples if a.get("type") == "POISON"
    }
    growth_apple_positions = {
        (a["x"], a["y"]) for a in apples if a.get("type") != "POISON"
    }
    non_poison_apples = [a for a in apples if a.get("type") != "POISON"]
    non_speed_apples = [a for a in apples if a.get("type") != "SPEED"]

    allow_poison = should_allow_poison(my_snake, safe_moves, head, poison_positions)
    candidate_apples = apples if allow_poison else (non_speed_apples or non_poison_apples or apples)

    if speed_active:
        candidate_apples = [a for a in candidate_apples if a.get("type") != "SPEED"] or candidate_apples

    edible_apples = [a for a in candidate_apples if a.get("type") != "POISON"]
    survival_target, survival_distance = choose_survival_food_target(
        head,
        edible_apples,
        grid_width,
        grid_height,
        forbidden,
    )
    starvation_imminent = (
        survival_target is not None
        and survival_distance is not None
        and my_energy <= (survival_distance + 8)
    )
    if starvation_imminent:
        avoid_growth = False

    if hunger_risky or starvation_imminent:
        if edible_apples:
            target = survival_target
            if target:
                target_pos = (target["x"], target["y"])
                emergency_ranked = []
                for move in safe_moves:
                    nxt = next_position(head, move)
                    next_pos = (nxt["x"], nxt["y"])
                    dist_to_food = shortest_path_distance(
                        next_pos,
                        {target_pos},
                        grid_width,
                        grid_height,
                        forbidden,
                        limit=120,
                    )
                    if dist_to_food is None:
                        dist_to_food = calculate_path_distance(next_pos, target_pos)
                    emergency_ranked.append(
                        (
                            dist_to_food,
                            -score_move(
                                head,
                                move,
                                game_state,
                                forbidden,
                                apples_dict,
                                poison_positions,
                                growth_apple_positions,
                                avoid_growth,
                                hunger_critical,
                            ),
                            move,
                        )
                    )

                emergency_ranked.sort()
                if emergency_ranked:
                    return emergency_ranked[0][2]

    ranked = rank_safe_moves(
        game_state,
        head,
        safe_moves,
        forbidden,
        apples_dict,
        poison_positions,
        growth_apple_positions,
        avoid_growth,
        hunger_critical,
    )
    best_move = ranked[0][1] if ranked else None
    best_score = ranked[0][0] if ranked else float("-inf")
    move_scores = {move: score for score, move in ranked}

    non_trap_ranked = []
    for score, move in ranked:
        nxt = next_position(head, move)
        next_pos = (nxt["x"], nxt["y"])
        future_space = flood_fill_space(next_pos, grid_width, grid_height, forbidden)
        future_open = count_open_neighbors(next_pos, grid_width, grid_height, forbidden)
        if not is_future_trap_position(future_space, future_open, len(my_snake.get("body", [])), speed_active):
            non_trap_ranked.append((score, move))

    if non_trap_ranked and not starvation_imminent:
        ranked = non_trap_ranked
        best_move = ranked[0][1]
        best_score = ranked[0][0]
        move_scores = {move: score for score, move in ranked}

    if avoid_growth and not hunger_risky and not starvation_imminent:
        target = None
    else:
        target = choose_priority_apple(head, candidate_apples, apples_dict, hunger_pressure, my_energy, speed_active)

    if target:
        preferred = get_move_towards(head, target)
        if preferred in safe_moves:
            nxt = next_position(head, preferred)
            nxt_coord = (nxt["x"], nxt["y"])
            if allow_poison or nxt_coord not in poison_positions:
                preferred_score = move_scores.get(preferred, float("-inf"))
                if best_move is None:
                    return preferred
                if preferred_score >= best_score - 5:
                    return preferred

    if not allow_poison:
        for move in safe_moves:
            nxt = next_position(head, move)
            nxt_pos = (nxt["x"], nxt["y"])
            if nxt_pos not in poison_positions:
                if avoid_growth and not hunger_risky and not starvation_imminent and nxt_pos in growth_apple_positions:
                    continue
                if best_move is None:
                    return move
                move_score = move_scores.get(move, float("-inf"))
                if move_score >= best_score - 10:
                    return move

    if best_move:
        sanitized = sanitize_move(head, best_move, grid_width, grid_height, forbidden)
        if sanitized is not None:
            return sanitized

    sanitized = sanitize_move(head, safe_moves[0], grid_width, grid_height, forbidden)
    if sanitized is not None:
        return sanitized
    return safe_moves[0]


def should_shed(game_state):
    snakes = game_state.get("snakes", [])
    if len(snakes) < 2:
        return False

    my_snake_state = snakes[0] or {}
    opponent_snake_state = snakes[1] or {}
    if not my_snake_state.get("alive", False) or not opponent_snake_state.get("alive", False):
        return False

    if my_snake_state.get("energy", DEFAULT_ENERGY) <= HUNGER_RISKY_ENERGY:
        return False

    my_body = [tuple((cell["x"], cell["y"])) for cell in my_snake_state.get("body", [])]
    opponent_body = [tuple((cell["x"], cell["y"])) for cell in opponent_snake_state.get("body", [])]
    if not my_body or not opponent_body:
        return False

    apples = game_state.get("apples", [])
    if not apples:
        return False

    grid_width = game_state.get("grid_width", 0)
    grid_height = game_state.get("grid_height", 0)
    my_head = {"x": my_body[0][0], "y": my_body[0][1]}
    opponent_head = {"x": opponent_body[0][0], "y": opponent_body[0][1]}
    forbidden = get_forbidden_cells(game_state)

    _, _, _, apples_dict, _ = parse_incoming_state(game_state)
    target_apple = detect_opponent_target_apple(opponent_head, apples, apples_dict)
    if not target_apple:
        return False

    if not can_intercept_apple(my_head, opponent_head, target_apple, len(my_body)):
        return False

    cutoff_positions = find_optimal_cutoff_positions(
        my_head,
        opponent_head,
        target_apple,
        grid_width,
        grid_height,
        forbidden,
    )
    if not has_sufficient_body_length(my_body, len(cutoff_positions)):
        return False

    shedding_positions = calculate_shedding_positions(
        my_head,
        opponent_head,
        target_apple,
        my_body,
        game_state,
        forbidden,
    )

    for position in cutoff_positions:
        if is_position_safe_for_shedding(position, (my_head["x"], my_head["y"]), grid_width, grid_height, forbidden, my_body):
            return True

    for position in shedding_positions:
        if is_position_safe_for_shedding(position, (my_head["x"], my_head["y"]), grid_width, grid_height, forbidden, my_body):
            return True

    wall_extensions = find_walls_to_extend(my_head, forbidden, game_state)
    for position in wall_extensions:
        if is_position_safe_for_shedding(position, (my_head["x"], my_head["y"]), grid_width, grid_height, forbidden, my_body):
            return True

    block_positions = calculate_blocking_pattern(
        my_head,
        (opponent_head["x"], opponent_head["y"]),
        target_apple,
        my_body,
        game_state,
        forbidden,
    )
    if block_positions and evaluate_block_safety(my_head, block_positions, game_state, forbidden, my_body):
        return True

    return False


def main():
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            game_state = json.loads(line)
            move = decide_move(game_state)
            my_snake = game_state.get("snakes", [{}])[0]
            head = my_snake.get("body", [{"x": 0, "y": 0}])[0]
            forbidden = get_forbidden_cells(game_state)
            sanitized_move = sanitize_move(
                head,
                move,
                game_state.get("grid_width", 0),
                game_state.get("grid_height", 0),
                forbidden,
            )
            if sanitized_move is not None:
                move = sanitized_move
            shed = should_shed(game_state)
            print(json.dumps({"move": move, "shed": shed}), flush=True)
    except Exception as e:
        print(json.dumps({"move": "UP", "shed": False}), flush=True)
        sys.stderr.write(f"Error: {e}\n")


if __name__ == "__main__":
    main()
