"""Black-Scholes greeks. Used to (re)compute gamma across candidate spot prices
for the zero-gamma solver, and to compute greeks on the free (GLD) fallback path
where the feed doesn't hand them to us. On the dxFeed path, gamma/delta come from
the feed for the point-in-time snapshot; IV is still used here for the flip curve."""
from __future__ import annotations
import numpy as np
from scipy.stats import norm


def _d1(S, K, T, r, q, sigma):
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.maximum(np.asarray(T, dtype=float), 1e-6)
    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-6)
    return (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))


def _d1d2(S, K, T, r, q, sigma):
    T = np.maximum(np.asarray(T, dtype=float), 1e-6)
    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-6)
    d1 = _d1(S, K, T, r, q, sigma)
    return d1, d1 - sigma * np.sqrt(T)


def gamma(S, K, T, r, q, sigma):
    """Gamma is identical for calls and puts."""
    T = np.maximum(np.asarray(T, dtype=float), 1e-6)
    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-6)
    d1 = _d1(S, K, T, r, q, sigma)
    return np.exp(-q * T) * norm.pdf(d1) / (np.asarray(S, float) * sigma * np.sqrt(T))


def delta(S, K, T, r, q, sigma, opt_type):
    """opt_type: 'C' or 'P' (array-like of same length as inputs, or scalar)."""
    d1 = _d1(S, K, T, r, q, sigma)
    T = np.maximum(np.asarray(T, dtype=float), 1e-6)
    call_delta = np.exp(-q * T) * norm.cdf(d1)
    is_call = np.asarray(opt_type) == "C"
    return np.where(is_call, call_delta, call_delta - np.exp(-q * T))


def vanna(S, K, T, r, q, sigma):
    """dDelta/dVol (= dVega/dSpot). Identical for calls and puts."""
    T = np.maximum(np.asarray(T, dtype=float), 1e-6)
    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-6)
    d1, d2 = _d1d2(S, K, T, r, q, sigma)
    return -np.exp(-q * T) * norm.pdf(d1) * d2 / sigma


def charm(S, K, T, r, q, sigma, opt_type):
    """dDelta/dTime ('delta bleed') -- per year; divide by 365 for a daily read.
    opt_type: 'C' or 'P' (array-like of same length as inputs, or scalar)."""
    T = np.maximum(np.asarray(T, dtype=float), 1e-6)
    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-6)
    d1, d2 = _d1d2(S, K, T, r, q, sigma)
    common = -np.exp(-q * T) * norm.pdf(d1) * (2 * (r - q) * T - d2 * sigma * np.sqrt(T)) / (2 * T * sigma * np.sqrt(T))
    is_call = np.asarray(opt_type) == "C"
    call_charm = q * np.exp(-q * T) * norm.cdf(d1) + common
    put_charm = -q * np.exp(-q * T) * norm.cdf(-d1) + common
    return np.where(is_call, call_charm, put_charm)
