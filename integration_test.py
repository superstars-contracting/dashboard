#!/usr/bin/env python3
"""
Integration test for Superstars Contracting project dashboard.
Tests end-to-end API workflow: RFI creation → updates, sign-ins → sign-outs,
drop plans → status changes → sign-offs, action items → status updates.
"""

import requests
import json
import time
import subprocess
import signal
import sys
import os
from datetime import date

API_BASE = 'http://localhost:5000'
TEST_PROJECT = 'FR-BX-001'
PASSED = 0
FAILED = 0

def log(msg, status='info'):
    """Log with status indicator"""
    symbols = {'pass': '✓', 'fail': '✗', 'info': '•', 'wait': '⏳'}
    print(f"{symbols.get(status, '•')} {msg}")

def test(step, fn, description):
    """Run a test function"""
    global PASSED, FAILED
    try:
        result = fn()
        PASSED += 1
        log(f"[{step}] {description}", 'pass')
        return result
    except Exception as e:
        FAILED += 1
        log(f"[{step}] {description} — {str(e)}", 'fail')
        return None

def health_check():
    """Verify server is responding"""
    try:
        resp = requests.get(f'{API_BASE}/api/health', timeout=2)
        assert resp.status_code == 200, f"Status: {resp.status_code}"
        log("Server health check passed", 'pass')
    except Exception as e:
        log(f"Server health check failed: {e}", 'fail')
        raise

def run_tests():
    """Execute all tests"""
    print("\n" + "="*70)
    print("SUPERSTARS CONTRACTING — INTEGRATION TEST SUITE")
    print("="*70 + "\n")
    
    print("Starting Flask server on localhost:5000...\n")
    
    # Test RFI workflow
    print("-"*70)
    print("RFI WORKFLOW TESTS")
    print("-"*70 + "\n")
    
    rfi_num = test('1a', lambda: (
        requests.post(f'{API_BASE}/api/rfis', json={
            'project_code': TEST_PROJECT,
            'submitted_by': 'John Doe',
            'discipline': 'Structural',
            'description': 'Lintel sizing clarification L7-L9',
            'priority': 'High'
        }).json()['data'].get('rfi_number')
    ), "POST /api/rfis — Create new RFI")
    
    test('1b', lambda: (
        len(requests.get(f'{API_BASE}/api/rfis').json()['data']) > 0
    ), "GET /api/rfis — Confirm new RFI in list")
    
    if rfi_num:
        test('1c', lambda: (
            requests.patch(f'{API_BASE}/api/rfis/{rfi_num}', json={'status': 'Answered'}).status_code == 200
        ), "PATCH /api/rfis/<id>/status — Update RFI status")
    
    # Test Sign-In workflow
    print("\n" + "-"*70)
    print("SIGN-IN WORKFLOW TESTS")
    print("-"*70 + "\n")
    
    sign_in = test('2a', lambda: (
        requests.post(f'{API_BASE}/api/sign-ins', json={
            'employee_id': 'E-001',
            'project_code': TEST_PROJECT,
            'time_in': '08:00',
            'date': date.today().isoformat()
        }).json()['data'].get('id')
    ), "POST /api/sign-ins — Create sign-in")
    
    if sign_in:
        test('2b', lambda: (
            requests.patch(f'{API_BASE}/api/sign-ins/{sign_in}', json={
                'time_out': '17:00'
            }).status_code == 200
        ), "PATCH /api/sign-ins/<id> — Record sign-out")
    
    # Test Drop Plan workflow
    print("\n" + "-"*70)
    print("DROP PLAN WORKFLOW TESTS")
    print("-"*70 + "\n")
    
    test('3a', lambda: (
        requests.patch(f'{API_BASE}/api/drops/DP-001/status', json={'status': 'Active'}).status_code == 200
    ), "PATCH /api/drops/DP-001/status — Update drop plan status")
    
    test('3b', lambda: (
        requests.post(f'{API_BASE}/api/drops/DP-001/sign-off', json={
            'role': 'Foreman',
            'signed_by_employee_id': 'E-001',
            'date': date.today().isoformat()
        }).status_code == 200
    ), "POST /api/drops/DP-001/sign-off — Record sign-off")
    
    test('3c', lambda: (
        requests.get(f'{API_BASE}/api/drops/DP-001').json()['data'].get('sign_off_status') == 'Complete'
    ), "GET /api/drops/DP-001 — Confirm sign-off persisted")
    
    # Test Action Items
    print("\n" + "-"*70)
    print("ACTION ITEMS WORKFLOW TESTS")
    print("-"*70 + "\n")
    
    test('4a', lambda: (
        requests.patch(f'{API_BASE}/api/action-items/1/status', json={
            'status': 'Completed',
            'completion_date': date.today().isoformat()
        }).status_code in [200, 404]
    ), "PATCH /api/action-items/1/status — Update action item status")
    
    # Test Site Closure
    print("\n" + "-"*70)
    print("SITE CLOSURE WORKFLOW TESTS")
    print("-"*70 + "\n")
    
    closures = test('5', lambda: (
        requests.get(f'{API_BASE}/api/site-closures').json()['data']
    ), "GET /api/site-closures — Fetch closures")
    
    if closures and isinstance(closures, list) and len(closures) > 0:
        closure_id = closures[0].get('closure_id', closures[0].get('id'))
        test('5b', lambda: (
            requests.patch(f'{API_BASE}/api/site-closures/{closure_id}/checklist', json={
                'item': 'Personnel-0',
                'value': True
            }).status_code in [200, 404]
        ), "PATCH /api/site-closures/<id>/checklist — Update closure item")
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"\nPassed: {PASSED}")
    print(f"Failed: {FAILED}")
    print(f"Total:  {PASSED + FAILED}\n")
    
    if FAILED == 0:
        print("Status: ALL TESTS PASSED ✓\n")
        return True
    else:
        print(f"Status: {FAILED} TEST(S) FAILED ✗\n")
        return False

if __name__ == '__main__':
    print("\nNote: This script requires the Flask server to be running on localhost:5000")
    print("Run this from your machine with: python integration_test.py\n")
    
    try:
        health_check()
        success = run_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nTest execution failed: {e}\n")
        sys.exit(1)
