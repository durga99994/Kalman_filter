import json
from typing import Dict, List, Tuple
from datamodel import OrderDepth, TradingState, Order

def update_kalman(state, covariance, measurement, process_noise=1e-4, measurement_noise=0.05):
    predicted_state = state
    predicted_covariance = covariance + process_noise
    kalman_gain = predicted_covariance / (predicted_covariance + measurement_noise)
    new_state = predicted_state + kalman_gain * (measurement - predicted_state)
    new_covariance = (1 - kalman_gain) * predicted_covariance
    return new_state, new_covariance

class Trader:

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        try:
            trader_state = json.loads(state.traderData) if state.traderData else {}
        except json.JSONDecodeError:
            trader_state = {}
            
        result = {}
        conversions = 0
        
        EXCHANGE_LIMITS = {
            'EMERALDS': 20,
            'TOMATOES': 20
        }
        
        print(f"==== TICK {state.timestamp} ====")
        
        for product, order_depth in state.order_depths.items():
            if product not in trader_state:
                trader_state[product] = {'kalman_state': None, 'kalman_covariance': 1.0}
                
            orders: List[Order] = []
            
            if len(order_depth.buy_orders) == 0 or len(order_depth.sell_orders) == 0:
                continue
                
            best_bid_price = max(order_depth.buy_orders.keys())
            best_bid_vol = order_depth.buy_orders[best_bid_price]
            
            best_ask_price = min(order_depth.sell_orders.keys())
            best_ask_vol = order_depth.sell_orders[best_ask_price]
            
            mid_price = (best_bid_price + best_ask_price) / 2.0
            spread = best_ask_price - best_bid_price
            
            # 1. Calculate Order Book Imbalance (What people SAY they want to do)
            total_bid_vol = sum(order_depth.buy_orders.values())
            total_ask_vol = sum(abs(vol) for vol in order_depth.sell_orders.values())
            total_vol = total_bid_vol + total_ask_vol
            obi = (total_bid_vol - total_ask_vol) / total_vol if total_vol > 0 else 0.0
            
            # 2. Calculate Trade Tape Imbalance (What people are ACTUALLY doing)
            tape_buy_vol = 0
            tape_sell_vol = 0
            
            if product in state.market_trades:
                for trade in state.market_trades[product]:
                    # If trade happened at/above ask, an aggressive buyer crossed the spread
                    if trade.price >= best_ask_price:
                        tape_buy_vol += trade.quantity
                    # If trade happened at/below bid, an aggressive seller crossed the spread
                    elif trade.price <= best_bid_price:
                        tape_sell_vol += trade.quantity
            
            # 3. Kalman Filter Math
            kalman_state = trader_state[product]['kalman_state']
            kalman_covariance = trader_state[product]['kalman_covariance']
            
            if kalman_state is None:
                kalman_state = mid_price
            else:
                kalman_state, kalman_covariance = update_kalman(
                    kalman_state, kalman_covariance, mid_price, 
                    process_noise=5e-4, measurement_noise=0.05
                )
            
            trader_state[product]['kalman_state'] = float(kalman_state)
            trader_state[product]['kalman_covariance'] = float(kalman_covariance)
            
            current_pos = state.position.get(product, 0)
            hard_limit = EXCHANGE_LIMITS.get(product, 20)
            dynamic_limit = hard_limit
            
            # 4. Dynamic Risk Limits
            if product == 'TOMATOES':
                if spread > 4:
                    dynamic_limit = int(hard_limit * 0.5) 
                if kalman_covariance > 0.1:
                    dynamic_limit = int(hard_limit * 0.2) 
            elif product == 'EMERALDS':
                if abs(mid_price - 10000) > 1.5:
                    dynamic_limit = int(hard_limit * 0.5)
            
            dynamic_limit = max(0, min(dynamic_limit, hard_limit))

            # ==========================================
            # EMERALDS LOGIC
            # ==========================================
            if product == 'EMERALDS':
                # Tape Reading Defense: Dodge Information Cascades
                if best_bid_price < 9998 and tape_sell_vol > tape_buy_vol and obi < -0.2:
                    dynamic_limit = 0 # Price is low, but actual tape shows heavy panic selling. Stand aside.
                elif best_ask_price > 10002 and tape_buy_vol > tape_sell_vol and obi > 0.2:
                    dynamic_limit = 0 # Price is high, but tape shows heavy FOMO buying. Don't short yet.

                if abs(kalman_state - 10000) <= 2:
                    if current_pos > 10:
                        buy_price_limit = int(round(9998))
                    else:
                        buy_price_limit = int(round(min(9999, best_bid_price + 1)))
                        
                    if current_pos < -10:
                        sell_price_limit = int(round(10002))
                    else:
                        sell_price_limit = int(round(max(10001, best_ask_price - 1)))
                    
                    buy_quantity = dynamic_limit - current_pos
                    if buy_quantity > 0:
                        orders.append(Order(product, buy_price_limit, buy_quantity))
                        
                    sell_quantity = -dynamic_limit - current_pos
                    if sell_quantity < 0:
                        orders.append(Order(product, sell_price_limit, sell_quantity))

            # ==========================================
            # TOMATOES LOGIC
            # ==========================================
            elif product == 'TOMATOES':
                fair_value = kalman_state
                
                # Capacity Hoarding
                signal_strength = abs(obi)
                if signal_strength > 0.7:
                    effective_limit = dynamic_limit         
                elif signal_strength > 0.4:
                    effective_limit = int(dynamic_limit * 0.5) 
                else:
                    effective_limit = int(dynamic_limit * 0.2) 
                
                premium = 1
                if kalman_covariance > 0.08:
                    premium = 2 

                # -- BUY LOGIC --
                # Only buy if the Tape (actual trades) isn't overwhelmingly bearish
                if tape_sell_vol <= (tape_buy_vol * 1.5): 
                    if fair_value > best_ask_price and obi > 0.2:
                        available_vol = abs(best_ask_vol)
                        qty_to_buy = min(effective_limit - current_pos, available_vol)
                        if qty_to_buy > 0:
                            orders.append(Order(product, best_ask_price, qty_to_buy))
                            current_pos += qty_to_buy
                            
                    elif obi > 0.5:
                        qty_to_buy = effective_limit - current_pos
                        if qty_to_buy > 0:
                            orders.append(Order(product, best_bid_price, qty_to_buy))
                            current_pos += qty_to_buy
                            
                    elif abs(obi) <= 0.2 and spread > 2:
                        buy_price = int(round(min(fair_value - premium, best_bid_price + 1)))
                        qty_to_buy = effective_limit - current_pos
                        if qty_to_buy > 0:
                            orders.append(Order(product, buy_price, qty_to_buy))
                            current_pos += qty_to_buy

                # -- SELL LOGIC --
                # Only sell if the Tape (actual trades) isn't overwhelmingly bullish
                if tape_buy_vol <= (tape_sell_vol * 1.5):
                    if fair_value < best_bid_price and obi < -0.2:
                        available_vol = abs(best_bid_vol)
                        max_sell_room = -effective_limit - current_pos
                        qty_to_sell = max(max_sell_room, -available_vol)
                        if qty_to_sell < 0:
                            orders.append(Order(product, best_bid_price, qty_to_sell))
                            current_pos += qty_to_sell
                            
                    elif obi < -0.5:
                        max_sell_room = -effective_limit - current_pos
                        if max_sell_room < 0:
                            orders.append(Order(product, best_ask_price, max_sell_room))
                            current_pos += max_sell_room
                            
                    elif abs(obi) <= 0.2 and spread > 2:
                        sell_price = int(round(max(fair_value + premium, best_ask_price - 1)))
                        max_sell_room = -effective_limit - current_pos
                        if max_sell_room < 0:
                            orders.append(Order(product, sell_price, max_sell_room))
                            current_pos += max_sell_room
                        
            if orders:
                print(f"  -> Emitting {len(orders)} orders for {product}")
            
            result[product] = orders
            
        return result, conversions, json.dumps(trader_state)