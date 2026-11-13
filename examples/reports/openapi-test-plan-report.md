# Demo API test plan report

## Objective

Verify API behavior described by requirements.

## Test cases

| ID | Title | Priority | Method | URL | Expected |
| --- | --- | --- | --- | --- | --- |
| listUsers | List users | medium | GET | `https://api.demo.local/users` | HTTP status in [200] |
| createUser | Create user | medium | POST | `https://api.demo.local/users` | HTTP status in [201] |
| getUser | Get user by id | medium | GET | `https://api.demo.local/users/42` | HTTP status in [200] |
| deleteUser | Delete user | medium | DELETE | `https://api.demo.local/users/42` | HTTP status in [204] |

### Case details

**listUsers. List users**

Expected: HTTP status in [200]
1. GET https://api.demo.local/users

**createUser. Create user**

Expected: HTTP status in [201]
1. POST https://api.demo.local/users; data: `{"name": "Ivan", "email": "user@example.com"}`

**getUser. Get user by id**

Expected: HTTP status in [200]
1. GET https://api.demo.local/users/42

**deleteUser. Delete user**

Expected: HTTP status in [204]
1. DELETE https://api.demo.local/users/42
