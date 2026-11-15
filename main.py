import os
import sys
import json
import math

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
HORIZONS = [1, 2, 3, 4, 5, 7, 9, 12, 16, 21, 28, 37, 49, 65, 86, 114, 151, 200, 240]

def price6(x):
    return round(min(1.0, max(0.0, x)), 6) + 0.0

def logit(p):
    p = min(0.9995, max(0.0005, p))
    return math.log(p / (1.0 - p))

def logistic(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    else:
        ez = math.exp(z)
        return ez / (1.0 + ez)

def compute_quantiles(arr, qs):
    if not arr:
        return [0.0] * len(qs)
    sorted_a = sorted(arr)
    n = len(sorted_a)
    res = []
    for q in qs:
        idx = q * (n - 1)
        i = int(idx)
        f = idx - i
        if i + 1 < n:
            val = sorted_a[i] * (1.0 - f) + sorted_a[i + 1] * f
        else:
            val = sorted_a[i]
        res.append(val)
    return res

def run_leg(prices_list, sigma_floor, width_factor, pool_denom, is_logit=False):
    if is_logit:
        x = [logit(p) for p in prices_list]
    else:
        x = list(prices_list)
    
    n = len(x)
    # 1. One-step changes and sigma_1
    deltas = [x[t] - x[t-1] for t in range(1, n)]
    abs_deltas = [abs(d) for d in deltas]
    mean_abs_delta = sum(abs_deltas) / len(abs_deltas) if abs_deltas else 0.0
    sigma_1 = max(sigma_floor, mean_abs_delta)
    
    # 2. Volatility trend (EWMA with 45-minute half-life)
    alpha = 1.0 - (2.0 ** (-1.0 / 45.0))
    if n >= 2:
        ewma = abs_deltas[0]
        for t in range(1, len(abs_deltas)):
            ewma = alpha * abs_deltas[t] + (1.0 - alpha) * ewma
        recent_vol = ewma
    else:
        recent_vol = sigma_1
        
    full_mean_abs = mean_abs_delta if mean_abs_delta > 1e-12 else 1.0
    vol_ratio = recent_vol / full_mean_abs if full_mean_abs > 1e-12 else 1.0
    
    market_data = {}
    for h in HORIZONS:
        full_h_changes = [x[t+h] - x[t] for t in range(0, n - h)] if n - h > 0 else []
        
        h_changes = list(full_h_changes)
        if n - 360 > h:
            recent_indices = [t for t in range(0, n - h) if t >= n - 360 - h]
            recent_h_changes = [x[t+h] - x[t] for t in recent_indices]
            if len(recent_h_changes) >= 60:
                h_changes.extend(recent_h_changes)
        
        vol_mult = 1.0 + (vol_ratio - 1.0) * max(0.0, 1.0 - h / 240.0)
        sigma_h = sigma_1 * math.sqrt(h) * vol_mult
        
        market_data[h] = {
            'changes': h_changes,
            'sigma_h': sigma_h,
            'last_val': x[-1] if n > 0 else 0.0
        }
    return market_data

def process_case(case_data):
    horizon = case_data.get('horizon_minutes', 240)
    markets = case_data.get('markets', [])
    
    market_models_a = []
    market_models_b = []
    
    for m in markets:
        prices = m['prices']
        if not prices:
            prices = [0.5]
        ma = run_leg(prices, sigma_floor=0.0008, width_factor=0.55, pool_denom=400, is_logit=False)
        mb = run_leg(prices, sigma_floor=0.02, width_factor=0.65, pool_denom=800, is_logit=True)
        market_models_a.append((m['id'], ma))
        market_models_b.append((m['id'], mb))
        
    forecasts_map = {}
    
    for h in HORIZONS:
        all_changes_a = []
        for _, ma in market_models_a:
            all_changes_a.extend(ma[h]['changes'])
        
        sigmas_a = [ma[h]['sigma_h'] for _, ma in market_models_a]
        ref_sigma_a = sorted(sigmas_a)[len(sigmas_a) // 2] if sigmas_a else 1.0
        if ref_sigma_a < 1e-12: ref_sigma_a = 1.0
        
        pooled_scaled_a = []
        for _, ma in market_models_a:
            sh = ma[h]['sigma_h']
            ratio = ref_sigma_a / sh if sh > 1e-12 else 1.0
            for c in ma[h]['changes']:
                pooled_scaled_a.append(c * ratio)
        if not pooled_scaled_a:
            pooled_scaled_a = [0.0]
        pooled_qs_a = compute_quantiles(pooled_scaled_a, QUANTILES)
        
        sigmas_b = [mb[h]['sigma_h'] for _, mb in market_models_b]
        ref_sigma_b = sorted(sigmas_b)[len(sigmas_b) // 2] if sigmas_b else 1.0
        if ref_sigma_b < 1e-12: ref_sigma_b = 1.0
        
        pooled_scaled_b = []
        for _, mb in market_models_b:
            sh = mb[h]['sigma_h']
            ratio = ref_sigma_b / sh if sh > 1e-12 else 1.0
            for c in mb[h]['changes']:
                pooled_scaled_b.append(c * ratio)
        if not pooled_scaled_b:
            pooled_scaled_b = [0.0]
        pooled_qs_b = compute_quantiles(pooled_scaled_b, QUANTILES)
        
        for idx, (m_id, ma) in enumerate(market_models_a):
            mb_id, mb = market_models_b[idx]
            
            changes_a = ma[h]['changes']
            sh_a = ma[h]['sigma_h']
            last_a = ma[h]['last_val']
            n_changes_a = len(changes_a)
            w_pool_a = 400.0 / (400.0 + n_changes_a)
            
            own_qs_a = compute_quantiles(changes_a, QUANTILES)
            rescaled_pooled_qs_a = [pq * (sh_a / ref_sigma_a) for pq in pooled_qs_a]
            blended_qs_a = [(1.0 - w_pool_a) * oq + w_pool_a * rq for oq, rq in zip(own_qs_a, rescaled_pooled_qs_a)]
            
            med_a = blended_qs_a[2]
            forecast_a = []
            for tau_idx, q_val in enumerate(blended_qs_a):
                dev = q_val - med_a
                f_val = last_a + med_a + 0.55 * dev
                forecast_a.append(f_val)
                
            changes_b = mb[h]['changes']
            sh_b = mb[h]['sigma_h']
            last_b = mb[h]['last_val']
            n_changes_b = len(changes_b)
            w_pool_b = 800.0 / (800.0 + n_changes_b)
            
            own_qs_b = compute_quantiles(changes_b, QUANTILES)
            rescaled_pooled_qs_b = [pq * (sh_b / ref_sigma_b) for pq in pooled_qs_b]
            blended_qs_b = [(1.0 - w_pool_b) * oq + w_pool_b * rq for oq, rq in zip(own_qs_b, rescaled_pooled_qs_b)]
            
            med_b = blended_qs_b[2]
            forecast_b_logit = []
            for tau_idx, q_val in enumerate(blended_qs_b):
                dev = q_val - med_b
                f_val_logit = last_b + med_b + 0.65 * dev
                forecast_b_logit.append(f_val_logit)
                
            forecast_b_price = [logistic(z) for z in forecast_b_logit]
            
            ensemble_q = [(fa + fb) / 2.0 for fa, fb in zip(forecast_a, forecast_b_price)]
            
            if m_id not in forecasts_map:
                forecasts_map[m_id] = {}
            forecasts_map[m_id][h] = ensemble_q

    final_forecasts = []
    for m in markets:
        m_id = m['id']
        m_h_map = forecasts_map.get(m_id, {})
        
        market_rows = []
        for minute in range(1, horizon + 1):
            if minute <= HORIZONS[0]:
                q_vals = m_h_map.get(HORIZONS[0], [0.5, 0.5, 0.5, 0.5, 0.5])
            elif minute >= HORIZONS[-1]:
                q_vals = m_h_map.get(HORIZONS[-1], [0.5, 0.5, 0.5, 0.5, 0.5])
            else:
                hi_idx = 0
                while hi_idx < len(HORIZONS) and HORIZONS[hi_idx] < minute:
                    hi_idx += 1
                h2 = HORIZONS[hi_idx]
                h1 = HORIZONS[hi_idx - 1]
                
                q1 = m_h_map.get(h1, [0.5, 0.5, 0.5, 0.5, 0.5])
                q2 = m_h_map.get(h2, [0.5, 0.5, 0.5, 0.5, 0.5])
                
                frac = (minute - h1) / (h2 - h1) if h2 > h1 else 0.0
                q_vals = [v1 + frac * (v2 - v1) for v1, v2 in zip(q1, q2)]
            
            clipped = [min(1.0, max(0.0, val)) for val in q_vals]
            for j in range(1, len(clipped)):
                if clipped[j] < clipped[j-1]:
                    clipped[j] = clipped[j-1]
            
            rounded = [price6(val) for val in clipped]
            market_rows.append(rounded)
            
        final_forecasts.append({
            'id': m_id,
            'q': market_rows
        })
        
    return {'forecasts': final_forecasts}

def main():
    input_dir = os.environ.get('MAKEFUN_INPUT_DIR', '/input')
    output_dir = os.environ.get('MAKEFUN_OUTPUT_DIR', '/output')
    
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(input_dir):
        print(f"Input directory {input_dir} does not exist.", file=sys.stderr)
        sys.exit(1)
        
    in_files = sorted([f for f in os.listdir(input_dir) if f.endswith('.in')])
    
    for filename in in_files:
        case_id = filename[:-3]
        filepath = os.path.join(input_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            case_data = json.load(f)
            
        result = process_case(case_data)
        
        out_filepath = os.path.join(output_dir, f"{case_id}.out")
        with open(out_filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, separators=(',', ':'))
            f.write('\n')

if __name__ == '__main__':
    main()
