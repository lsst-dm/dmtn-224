:tocdepth: 1

.. sectnum::

Abstract
========

The identity management, authentication, and authorization component of the Rubin Science Platform is responsible for maintaining a list of authorized users and their associated identity information, authenticating their access to the Science Platform, and determining which services they are permitted to use.
This tech note describes the technical details of the implementation of that system.

.. note::

   This is part of a tech note series on identity management for the Rubin Science Platform.
   The other primary documents are DMTN-234_, which describes the high-level design; and SQR-069_, which provides a history and analysis of the decisions underlying the design and implementation.
   See :ref:`References <references>` for a complete list of related documents.

Implementation overview
=======================

The primary components of the identity management system for the Rubin Science Platform are:

#. Some external source of user authentication
#. A repository of identity information about users (name, email, group membership, etc.)
#. A Kubernetes service (Gafaelfawr_) which runs in each Science Platform deployment, performs user authentication, applies high-level access control rules, and provides identity information to other Science Platform services via an API
#. A configuration of the ingress-nginx_ Kubernetes ingress controller that uses Gafaelfawr_ as an auth subrequest handler to enforce authentication and authorization requirements
#. A user interface for creating and managing tokens, currently implemented as part of Gafaelfawr_

.. _ingress-nginx: https://kubernetes.github.io/ingress-nginx/

The Science Platform in general, and specifically the last three components listed above, are deployed in a Kubernetes cluster using Phalanx_.
The first two components are external to the Kubernetes cluster in which the Science Platform runs.

Here is that architecture in diagram form:

.. figure:: /_static/science-platform.png
   :name: High-level Science Platform architecture

   An overview of a Rubin Science Platform deployment.
   This shows the major aspects of the Science Platform but omits considerable detail, including most supporting services, the identity management store, and some details of the Gafaelfawr architecture.

As discussed in DMTN-234_, there is no single Rubin Science Platform.
There are multiple deployments of the Science Platform at different sites with different users and different configurations.
With respect to the identity management system, these differ primarily in the choice of the first two components.

General access deployments of the Science Platform use CILogon_ as the source of user authentication, and COmanage_ as the repository of identity information.
Here is the architecture for general access deployments, expanding the identity management portion and simplifying the rest of the Science Platform to a single protected service:

.. _CILogon: https://www.cilogon.org/
.. _COmanage: https://www.incommon.org/software/comanage/

.. figure:: /_static/general-access.png
   :name: General access identity management architecture

   Detail of the components for identity management for a general access deployment of the Science Platform.
   The Science Platform aspects and services are represented here by a single service to make the diagram simpler.

Restricted access deployments use either GitHub or a local `OpenID Connect`_ authentication provider as the source of user authentication; and one of GitHub, a local LDAP server, or the OpenID Connect authentication provider as the source of identity information.

.. _OpenID Connect: https://openid.net/specs/openid-connect-core-1_0.html

A restricted access deployment that uses GitHub looks essentially identical to the first architecture diagram with GitHub as the identity provider.
One that uses OpenID Connect is similar, but will likely separate the identity provider box into an OpenID Connect provider and an LDAP server that will be queried for metadata.

Identity management
===================

The identity management component of the system authenticates the user and maps that authentication to identity information.

In general access deployments, authentication is done via the OpenID Connect protocol using CILogon, which in turn supports SAML and identity federations as well as other identity providers such as GitHub and Google.
Restricted access deployments use either an OAuth 2.0 authentication request to GitHub or an OpenID Connect authentication request to a local identity provider.

Once the user has been authenticated, their identity must be associated with additional information: full name, email address, numeric UID, group membership, and numeric GIDs for the groups.
In general access deployments, most of this data comes from :ref:`COmanage <comanage-idm>` (via LDAP), and numeric UIDs and GIDs come from :ref:`Firestore <firestore>`.
For restricted access deployments using GitHub, access to the user's profile and organization membership is requested as part of the OAuth 2.0 request, and then retrieved after authentication with the token obtained by the OAuth 2.0 authentication.  See :ref:`GitHub <github>` for more details.
With OpenID Connect, this information is either extracted from the claims of the JWT_ issued as a result of the OpenID Connect authentication flow, or is retrieved from LDAP.

.. _JWT: https://datatracker.ietf.org/doc/html/rfc7519

See DMTN-225_ for more details on the identity information stored for each user and its sources.

.. _comanage-idm:

COmanage
--------

COmanage_ is a web application with associated database and API that manages an organization of users.
Information about those users is then published to an LDAP server, which can be queried by Gafaelfawr_ as needed.
COmanage has multiple capabilities, only a few of which will be used by the Science Platform.
Its main purposes for the Science Platform are to:

#. manage the association of users with federated identities;
#. assign usernames to authenticated users;
#. determine the eligibility of users for Science Platform access and for roles within that access;
#. manage group membership, both for groups maintained by Rubin Observatory and for user-managed groups; and
#. store additional metadata about the user such as email, full name, and institutional affiliation.

CILogon is agnostic to whether a user is registered or has an account in some underlying database.
It prompts the user for an identity provider to use, authenticates them, and then provides that identity information to the OpenID Connect relying party (Gafaelfawr).
Gafaelfawr, however, only wants to allow access to users who are registered in COmanage, and otherwise ask the user to register so that they can be evaluated and possibly approved for Science Platform access.

To implement this, the Gafaelfawr OpenID Connect integration with COmanage is configured to pull the user's registered username (what COmanage calls their UID) from COmanage LDAP.
CILogon will find their username by looking up their LDAP entry based on the CILogon opaque identifier assigned to that user from that identity provider (which COmanage stores in a multivalued ``uid`` attribute in the person tree in LDAP) and retrieving their username (which COmanage stores in the ``voPersonApplicationUID`` attribute).
CILogon then adds that username as the ``username`` claim in the JWT provided to Gafaelfawr at the conclusion of the OpenID Connect authentication.

If that claim is missing, the user is not registered, and Gafaelfawr then redirects them to an :ref:`onboarding flow <comanage-onboarding>`.
Otherwise, Gafaelfawr retrieves group information from LDAP and then uses that to assign scopes to the newly-created session token (see :ref:`Browser flows <browser-flows>`).

For the precise details of how COmanage is configured, see SQR-055_.

.. _comanage-onboarding:

COmanage onboarding
^^^^^^^^^^^^^^^^^^^

If the user is not already registered in COmanage, they will be redirected to an onboarding flow in the COmanage web UI.
We use the "Self Signup With Approval" flow, one of the standard COmanage enrollment flows, with some modifications detailed in SQR-055_.
This will use their identity information from CILogon and prompt them for their preferred name, email address, and username.
They will be required to confirm that they can receive email at the email address they give.
The choice of username is subject to constraints specified in DMTN-225_.
The user's COmanage account will then be created in a pending state, and must be approved by an authorized approver before it becomes active and is provisioned in LDAP (and thus allows access to the Science Platform).

Approvers are notified via email by COmanage that a new user is awaiting approval.
Approval will be based on the institutional affiliation information collected by COmanage from the identity information released by the user's identity provider via CILogon.
Approvers may have to reach out to the prospective user or their institution to gather additional information before deciding whether the user has data rights.

Once the user is approved, the approver will add them to a group appropriate for their data rights access.
The user will be notified of their approval via email.
They will then be able to return to the Science Platform deployment and log in, and CILogon will now release their username in the ``username`` claim, allowing Gafaelfawr to look up their identity information in the LDAP server populated by COmanage, assign them scopes, and allow them to continue to the Science Platform.

COmanage user UI
^^^^^^^^^^^^^^^^

COmanage provides a web-based user interface to the user.
From that interface, they can change their preferred name and email address and review their identity information.

To add another federated identity for the same user, the user can initiate the "Link another account" enrollment flow.
They will be prompted to log in again at CILogon, and can pick a different authentication provider.
After completing that authentication, the new identity and authentication method will be added to their existing account.
All such linked identities can be used interchangeably to authenticate to the same underlying Science Platform account.

If the user no longer intends to use an identity provider, they can unlink it from their account in the UI.

COmanage provides a group management mechanism called COmanage Registry Groups.
This allows users to create and manage groups.
This group mechanism is used for both user-managed and institution-managed groups.
From the COmanage UI, users can change the membership of any group over which they have administrative rights, and can create new user-managemd groups.

COmanage administrators (designated by their membership in an internal COmanage group) can edit user identity information of other users via the COmanage UI, and can change any group (including user-managed groups, although normally an administrator will only do that to address some sort of problem or support issue).

COmanage LDAP
^^^^^^^^^^^^^

The data stored in COmanage is exported to LDAP in two trees.
The person tree holds entries for each Science Platform user.
The group tree holds entries for every group (Rubin-managed or user-managed).

During login, and when a Science Platform application requests user identity data, Gafaelfawr retrieves user identity information by looking up the user in the person tree, and retrieves the user's group membership by searching for all groups that have that user as a member.

A typical person tree entry looks like::

    dn: voPersonID=LSST100006,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    sn: Allbery
    cn: Russ Allbery
    objectClass: person
    objectClass: organizationalPerson
    objectClass: inetOrgPerson
    objectClass: eduMember
    objectClass: voPerson
    displayName: Russ Allbery
    mail: rra@lsst.org
    uid: http://cilogon.org/serverA/users/15423111
    uid: http://cilogon.org/serverT/users/40811318
    isMemberOf: CO:members:all
    isMemberOf: CO:members:active
    isMemberOf: CO:admins
    isMemberOf: g_science-platform-idf-dev
    isMemberOf: g_test-group
    voPersonApplicationUID: rra
    voPersonID: LSST100006
    voPersonSoRID: http://cilogon.org/serverA/users/31388556

``voPersonApplicationUID`` is, as mentioned above, the user's username.
The ``uid`` multivalued attribute holds the unique CILogon identifiers.
``voPersonID`` is an internal unique identifier for that user that's used only by COmanage.
The user's preferred full name is in ``displayName`` and their preferred email address is in ``mail``.

A typical group tree entry looks like::

    dn: cn=g_science-platform-idf-dev,ou=groups,o=LSST,o=CO,dc=lsst,dc=org
    cn: g_science-platform-idf-dev
    member: voPersonID=LSST100006,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    member: voPersonID=LSST100008,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    member: voPersonID=LSST100009,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    member: voPersonID=LSST100010,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    member: voPersonID=LSST100011,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    member: voPersonID=LSST100012,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    member: voPersonID=LSST100013,ou=people,o=LSST,o=CO,dc=lsst,dc=org
    objectClass: groupOfNames
    objectClass: eduMember
    hasMember: rra
    hasMember: adam
    hasMember: frossie
    hasMember: jsick
    hasMember: cbanek
    hasMember: afausti
    hasMember: simonkrughoff

.. _github:

GitHub
------

A Science Platform deployment using GitHub registers Gafaelfawr as an OAuth App.
When the user is sent to GitHub to perform an OAuth 2.0 authentication, they are told what information about their account the application is requesting, and are prompted for which organizational information to release.
After completion of the OAuth 2.0 authentication flow, Gafaelfawr then retrieves the user's identity information (full name, email address, and UID) and their team memberships from any of their organizations.

Group membership for Science Platform purposes is synthesized from GitHub team membership.
Each team membership that an authenticated user has on GitHub (and releases through the GitHub OAuth authentication) will be mapped to a group.
The name of the group will be ``<organization>-<team-slug>`` where ``<organization>`` is the ``login`` attribute (forced to lowercase) of the organization containing the team and ``<team-slug>`` is the ``slug`` attribute of the team.
These values are retrieved through GitHub's ``/user/teams`` API route.
The ``slug`` attribute is constructed by GitHub based on the name of the team, removing case differences and replacing special characters like space with a dash.

Some software may limit the length of group names to 32 characters, and forming group names this way may result in long names if both the organization and team name is long.
Therefore, if the group name formed as above is longer than 32 characters, it will be truncated and made unique.
The full group name will be hashed (with SHA-256) and truncated at 25 characters, and then a dash and the first six characters of the URL-safe-base64-encoded hash will be appended.

The ``id`` attribute for each team will be used as the GID of the corresponding group.

Authentication flows
====================

For general access environments that use COmanage, this section assumes the COmanage account for the user already exists.
If it does not, see :ref:`COmanage onboarding <comanage-onboarding>`.

See the Gafaelfawr_ documentation for specific details on the ingress-nginx annotations used to protect services and the HTTP headers that are set and available to be passed down to the service after successful authentication.

.. _browser-flows:

Browser flows
-------------

If the user visits a Science Platform page intended for a web browser (as opposed to APIs) and is not already authenticated (either missing a cookie or having an expired cookie), they will be sent to an identity provider to authenticate.

.. _generic-browser-flow:

Generic authentication flow
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Here are the generic steps of a browser authentication flow.
The details of steps 5 and 6 vary depending on the authentication provider, as discussed in greater depth below.

#. The user attempts to access a Science Platform web page that requires authentication.
#. The Gafaelfawr ``/auth`` route receives the headers of the original request.
   No token is present in an ``Authorization`` header, nor is there an authentication session cookie.
   The ``/auth`` route therefore returns an HTTP 401 error.
#. ingress-nginx determines from its annotations that this means the user should be redirected to the ``/login`` route with the original URL included in the ``X-Auth-Request-Redirect`` header.
#. The Gafaelfawr ``/login`` route sets a session cookie containing a randomly-generated ``state`` parameter (for session fixation protection).
   It also includes the return URL in that session cookie.
   It then returns a redirect to the authentication provider that contains the ``state`` string plus other required information for the authentication request.
#. The user interacts with the authentication provider to prove their identity, which eventually results in a redirect back to the ``/login`` route.
   That return request includes an authorization code and the original ``state`` string, as well as possibly other information.
#. The ``/login`` route requires the ``state`` code match the value from the user's session cookie to protect against session fixation.
   It then extracts the authorization code and redeems it for a token from the authentication provider.
   Gafaelfawr may then validate that token and may use it to get more information about the user, depending on the identity provider as discussed below.
#. Based on the user's identity data, the ``/login`` route creates a new session token and stores the associated data in the Gafaelfawr token store.
   If Firestore is used for UIDs, the UID for this username is retrieved from Firestore and stored with the token.
   It then stores that token in the user's session cookie.
   Finally, it redirects the user back to the original URL.
#. When the user requests the original URL, this results in another authentication subrequest to the ``/auth`` route.
   This time, the ``/auth`` route finds the session cookie and extracts the token from that cookie.
   It retrieves the token details from the token store and decrypts and verifies it.
   It then checks the scope information of that token against the requested authentication scope given as a ``scope`` parameter to the ``/auth`` route.
   If the requested scope or scopes are not satisfied, it returns a 403 error.
   If LDAP is configured, user metadata such as group memberships and email address are retrieved from LDAP.
   That metadata, either from the data stored with the token or from LDAP, is added to additional response headers.
   Gafaelfawr then returns 200 with those response headers, and NGINX then proxies the request to the protected application and user interaction continues as normal, possibly including some of the response headers in the proxied request.

CILogon
^^^^^^^

Here is the CILogon authorization flow in detail.

.. figure:: /_static/flow-login-cilogon.svg
   :name: CILogon browser authentication flow

The following specific steps happen during step 5 of the :ref:`generic browser flow <generic-browser-flow>`.

#. CILogon prompts the user for which identity provider to use, unless the user has previously chosen an identity provider and told CILogon to remember that selection.
#. CILogon redirects the user to that identity provider.
   That identity provider does whatever it chooses to do to authenticate the user and redirects the user back to CILogon.
   CILogon then takes whatever steps are required to complete the authentication using whatever protocol that identity provider uses, whether it's SAML, OAuth 2.0, OpenID Connect, or something else.

The following specific steps happen during step 6 of the generic browser flow, in addition to the ``state`` validation and code redemption:

#. Gafaelfawr retrieves the OpenID Connect configuration information for CILogon and checks the signature on the JWT identity token.
#. Gafaelfawr extracts the user's username from the ``username`` claim of the identity token.
   If that claim is missing, Gafaelfawr redirects the user to the enrollment flow at COmanage, which aborts the user's attempt to access whatever web page they were trying to visit.
#. Gafaelfawr retrieves the user's UID from Firestore, assigning a new UID if necessry if that username had not been seen before.
#. Gafaelfawr retrieves the user's group membership from LDAP using the ``username`` as the search key.

Subsequently, whenever Gafaelfawr receives an authentication subrequest to the ``/auth`` route, it retrieves the user's identity information and group membership from LDAP.
For each group, the GID for that group is retrieved from Firestore, and a new GID is assigned if that group has not been seen before.
That data is then returned in HTTP headers that ingress-nginx includes in the request to the Science Platform service being accessed.
Similarly, Gafaelfawr retrieves the user's identity information and group membership from LDAP and Firestore whenever it receives a request for the user information associated with a token.
(In practice, both the LDAP and Firestore data is usually cached.  See :ref:`Caching <caching>` for more information.)

Note that, in the CILogon and COmanage case, user identity data is not stored with the token.
Gafaelfawr retrieves it on the fly whenever it is needed (possibly via a cache).
Changes to COmanage are therefore reflected immediately in the Science Platform (after the expiration of any cache entries).

.. _github-flow:

GitHub
^^^^^^

Here is the GitHub authentication flow in detail.

.. figure:: /_static/flow-login-github.svg
   :name: GitHub browser authentication flow

   Sequence diagram of the browser authentication flow with GitHub.

The following specific steps happen during step 5 of the :ref:`generic browser flow <generic-browser-flow>`.

#. GitHub prompts the user for their authentication credentials if they're not already authenticated.
#. If the user has not previously authorized the OAuth App for this Science Platform deployment, the user is prompted to confirm to GitHub that it's okay to release their identity information and organization membership to Gafaelfawr.

The following specific steps happen during step 6 of the generic browser flow, in addition to the ``state`` validation and code redemption.

#. Using the authentication token received after redeeming the code, the user's full name and ``id`` (used as their UID) is retrieved from the GitHub ``/user`` route.
#. Using the same token, the user's primary email address is retrieved from the GitHub ``/usr/emails`` route.
#. Using the same token, the user's team memberships (where Gafaelfawr is authorized to access them) are retrieved from the GitHub ``/user/teams`` route.
#. The token is then stored in the user's encrypted cookie as their GitHub session token.

The user's identity data retrieved from GitHub is stored with the session token and inherited by any other child tokens of the session token, or any user tokens created using that session token.
Changes on the GitHub side are not reflected in the Science Platform until the user logs out and logs back in, at which point their information is retrieved fresh from GitHub and stored in the new session token and any of its subsequent child tokens or user tokens.

When the user logs out, the GitHub session token is used to explicitly revoke the user's OAuth App authorization at GitHub.
This forces the user to return to the OAuth App authorization screen when logging back in, which in turn will cause GitHub to release any new or changed organization information.
Without the explicit revocation, GitHub reuses the prior authorization with the organization and team data current at that time and doesn't provide data from new organizations.
See :ref:`Cookie data <cookie-data>` for more information.

OpenID Connect
^^^^^^^^^^^^^^

Here is the OpenID Connect authentication flow in detail.

.. figure:: /_static/flow-login-oidc.svg
   :name: OpenID Connect browser authentication flow

   Sequence diagram of the browser authentication flow for a generic OpenID Connect provider, assuming identity data is stored in LDAP.

The following specific steps happen during step 6 of the :ref:`generic browser flow <generic-browser-flow>`.

#. Gafaelfawr retrieves the OpenID Connect configuration information for the OpenID Connect provider and checks the signature on the JWT identity token.
#. Gafaelfawr extracts the user's username from a claim of the identity token.
   (This is configured per OpenID Connect provider.)
#. If LDAP is not configured, Gafaelfawr extracts the user's identity information from the JWT to store it with the session token.
#. If LDAP is configured, Gafaelfawr retrieves the user's group membership from LDAP using the username as a key.

If LDAP is configured, whenever Gafaelfawr receives an authentication subrequest to the ``/auth`` route, it retrieves the user's identity information and group membership from LDAP.
That data is then returned in HTTP headers that ingress-nginx includes in the request to the Science Platform service being accessed.
Similarly, if LDAP is configured, Gafaelfawr retrieves the user's identity information and group membership from LDAP whenever it receives a request for the user information associated with a token.
(In practice, the LDAP data is usually cached.  See :ref:`Caching <caching>` for more information.)

If LDAP is in use, user identity data is not stored with the token.
Gafaelfawr retrieves it on the fly whenever it is needed (possibly via a cache).
Changes in LDAP are therefore reflected immediately in the Science Platform (after the expiration of any cache entries).

If instead the user's identity information comes from the JWT issued by the OpenID Connect authentication process, that data is stored with the token and inherited by any other child tokens of the session token, or any user tokens created using that session token, similar to how data from GitHub is handled.

Token flows
-----------

All token authentication flows are similar, and much simpler.
The client puts the token in an ``Authorization`` header, either with the ``bearer`` keyword (preferred) as an `RFC 6750`_ bearer token, or as either the username or password of `RFC 7617`_ HTTP Basic Authentication.
In the latter case, whichever of the username or password that is not set to the token should be set to ``x-oauth-basic``.

.. _RFC 6750: https://datatracker.ietf.org/doc/html/rfc6750
.. _RFC 7617: https://datatracker.ietf.org/doc/html/rfc7617

Gafaelfawr returns a 401 response code from the auth subrequest if no ``Authorization`` header is present, and a 403 response code if credentials are provided but not valid.
In both cases, this is accompanied by a ``WWW-Authenticate`` challenge.
By default, this is an `RFC 6750`_ bearer token challenge, but Gafaelfawr can be configured to return a `RFC 7617`_ HTTP Basic Authentication challenge instead (via a parameter to the ``/auth`` route, when it is configured in the ``Ingress`` as the auth subrequest handler).

Gafaelfawr returns a 200 response code if the credentials are valid, which tells ingress-nginx to pass the request (possibly with additional headers) to the protected service.

The behavior of redirecting the user to log in if they are not authenticated is implemented in ingress-nginx by configuring its response to a 401 error from the auth subrequest.
For API services that are not used by browsers, ingress-nginx should not be configured with the ``nginx.ingress.kubernetes.io/auth-signin`` annotation.
In this case, it will return the 401 challenge to the client instead of redirecting.

When authenticating a request with a token, Gafaelfawr does not care what type of token is pressented.
It may be a user, notebook, internal, or service token; all of them are handled the same way.

.. _token-reuse:

Reuse of notebook and internal tokens
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A user often makes many requests to a service over a short period of time, particularly when using a browser and requesting images, JavaScript, icons, and similar resources.
If that service needs delegated tokens (notebook or internal tokens), a naive approach would create a plethora of child tokens, causing significant performance issues.
Gafaelfawr therefore reuses notebook and internal tokens where possible.

The criterial for reusing a notebook token is:

#. Same parent token
#. Parent token expiration has not changed
#. Parent token's scopes are still a superset of the child token's scopes
#. Child token is still valid
#. Child token has a remaining lifetime of at least half the normal token lifetime (or the lifetime of the parent token, whichever is shorter)

To reuse an internal token, it must meet the same criteria, plus:

#. Same requested child token service
#. Same requested child token scopes

If a notebook or internal token already exists that meet these criteria, that token is returned as the token to delegate to the service, rather than creating a new token.

Notebook and internal tokens are also cached to avoid the SQL and Redis queries required to find a token that can be reused.
See :ref:`Caching <caching>` for more information.

Storage
=======

This section deals only with storage for Gafaelfawr in each Science Platform deployment.
For the storage of identity management information for each registered user in a general access deployment, see :ref:`COmanage <comanage-idm>`.

Gafaelfawr storage is divided into two, sometimes three, backend stores: a SQL database, Redis, and optionally Firestore.
Redis is used for the token itself, including the authentication secret.
It contains enough information to verify the authentication of a request and return the user's identity.
The SQL database stores metadata about a user's tokens, including the list of currently valid tokens, their relationships to each other, and a history of where they have been used from.

If the user's identity information doesn't come from LDAP, Redis also stores the identity information.

Token format
------------

A token is of the form ``gt-<key>.<secret>``.
The ``gt-`` part is a fixed prefix to make it easy to identify tokens, should they leak somewhere where they were not expected.
The ``<key>`` is the Redis key under which data about the token is stored.
The ``<secret>`` is an opaque value used to prove that the holder of the token is allowed to use it.
Wherever the token is named, such as in UIs, only the ``<key>`` component is given, omitting the secret.
When the token is presented for authentication, the secret provided is checked against the stored secret for that key.
Checking the secret prevents someone who can list the keys in the Redis session store from using those keys as session handles.

Redis
-----

Redis is canonical for whether a token exists and is valid.
If a token is not found in Redis, it cannot be used to authenticate, even if it still exists in the SQL database.
The secret portion of a token is stored only in Redis.

Redis stores a key for each token except for the bootstrap token (see :ref:`Bootstrapping <bootstrapping>`).
The Redis key is ``token:<key>`` where ``<key>`` is the key portion of the token, corresponding to the primary key of the ``token`` table.
The value is an encrypted JSON document with the following keys:

- **secret**: The corresponding secret for this token
- **username**: The user whose authentication is represented by this token
- **type**: The type of the token (``session``, ``user``, ``service``, etc.)
- **service**: The service to which the token was issued (only present for internal tokens)
- **scope**: An array of scopes
- **created**: When the token was created (in seconds since epoch)
- **expires**: When the token expires (in seconds since epoch)

In addition, if user identity information does not come from LDAP, the following keys store identity information associated with this token.
This information comes from OpenID Connect claims or from GitHub queries for information about the user.

.. rst-class:: compact

- **name**: The user's preferred full name
- **email**: The user's email address
- **uid**: The user's unique numeric UID
- **groups**: The user's group membership as a list of dicts with two keys, **name** and **id** (the unique numeric GID of the group)

For general access deployments, none of these fields are ever set.
For GitHub deployments, all of these fields are set (if the data is available; in the case of naem and email, it may not be).
For OpenID Connect deployments, whether a field is set depends on whether that field is configured to come from LDAP or to come from the OpenID Connect token claims.
In the latter case, the information is stored with the token.
Tokens created via the admin token API may have these fields set, in which case the values set via the admin token API override any values in LDAP, even if LDAP is configured.
In other words, Gafaelfawr uses any data stored with the token by preference, and queries LDAP (if configured) only for data not stored with the token.

The Redis key for a token is set to expire when the token expires.

The token JSON document is encrypted with Fernet_ using a key that is private to the authentication system.
This encryption prevents an attacker with access only to the Redis store, but not to the running authentication system or its secrets, from using the Redis keys to reconstruct working tokens.

.. _Fernet: https://cryptography.io/en/latest/fernet/

SQL database
------------

Cloud SQL is used wherever possible, via the `Cloud SQL Auth proxy`_ running as a sidecar container in Gafaelfawr pods.
For deployments outside of :abbr:`GCS (Google Cloud Services)`, an in-cluser PostgreSQL server deployed as part of the Science Platform is used instead.
Authentication to the SQL server is via a password injected as a Kubernetes secret into the Gafaelfawr pods.

.. _Cloud SQL auth proxy: https://cloud.google.com/sql/docs/postgres/connect-admin-proxy

The SQL database stores the following data:

#. Keys of all current tokens and their username, type, scope, creation and expiration date, name (for user tokens), and service (for internal tokens).
   Any identity data stored with the token is stored only in Redis, not in the SQL database.
#. Parent-child relationships between the tokens.
#. History of changes (creation, revocation, expiration, modification) to tokens, including who made the change and the IP address from which it was made.
#. List of authentication administrators, who automatically get the ``admin:token`` scope when they authenticate via a browser;
#. History of changes to admins, including who made the change and the IP address from which it was made.

Note that IP addresses are stored with history entries.
IP addresses are personally identifiable information and may be somewhat sensitive, but are also extremely useful in debugging problems and identifying suspicious behavior.

The current implementation does not redact IP addresses, but this may be reconsidered at a later stage as part of a more comprehensive look at data privacy.

.. _cookie-data:

Cookie data
-----------

Session cookies are stored in a browser cookie.
Gafaelfawr also stores other information in that cookie to support login redirects, CSRF protection for the UI, and GitHub logout.

The cookie is an encrypted JSON document with the following keys, not all of which may be present depending on the user's authentication state.

.. rst-class:: compact

* **token**: User's session token if they are currently authenticated.
* **csrf**: CSRF token, required for some state-changing operations when authenticated via session token presented in a browser cookie.
  See :ref:`CSRF protection <csrf>` for more details.
* **github**: OAuth 2.0 token for the user obtained via GitHub authentication.
  Used to revoke the user's OAuth App grant on logout as discussed in :ref:`GitHub browser flow <github-flow>`.
* **return_url**: URL to which to return once the login process is complete.
  Only set while a login is in progress.
* **state**: Random state for the login process, used to protect against session fixation.
  Only set while a login is in progress.

The JSON document is encrypted with Fernet_ using the same key as is used for the Redis backend store.
The resulting encrypted data is set as the ``gafaelfawr`` cookie.
This cookie is marked ``Secure`` and ``HttpOnly``.

.. _firestore:

Firestore
---------

General access Science Platform deployments use Firestore to manage UID and GID assignment, since COmanage is not well-suited for doing this.
These assignments are stored in `Google Firestore`_, which is a NoSQL document database.

.. _Google Firestore: https://cloud.google.com/firestore

Gafaelfawr uses three collections.

The ``users`` collection holds one document per username.
Each document has one key, ``uid``, which stores the UID assigned to that user.

The ``groups`` collection holds one document per group name.
Each document has one key, ``gid``, which stores the GID assigned to that group.

The ``counters`` collection holds three documents, ``bot-uid``, ``uid``, and ``gid``.
Each document has one key, ``next``, which is the next unallocated UID or GID for that class of users or groups.
They are initialized with the start of the ranges defined in DMTN-225_.

If a user or group is not found, it is allocated a new UID or GID inside a transaction, linked with the update of the corresponding counter.
If another Gafaelfawr instance allocates a UID or GID from the same space at the same time, the transaction will fail and is automatically retried.
The ``bot-uid`` counter is used for usernames starting with ``bot-``, which is the convention for service users (as opposed to human users).
There is no mechanism for deleting or reusing UIDs or GIDs; any unknown user or group is allocated the next sequential UID or GID, and that allocation fails if the bot UID or group GID space has been exhausted.

Gafaelfawr uses workload identity to authenticate to the Firestore database.
The Firestore database is managed in a separate GCS project dedicated to Firestore, which is a best practice for Firestore databases since it is part of App Engine and only one instance is permitted per project.

.. _bootstrapping:

Bootstrapping
-------------

Gafaelfawr provides a command-line utility to bootstrap a new installation of the token management system by creating the necessary database schema.
To bootstrap administrative access, this step adds a configured list of usernames to the SQL databsae as admins.
These administrators can then use the API or web interface to add additional administrators.

Gafaelfawr's configuration may also include a bootstrap token.
This token will have unlimited access to the API routes ``/auth/api/v1/admins`` and ``/auth/api/v1/tokens`` and thus can configure the administrators and create service and user tokens with any scope and any identity.

Actions performed via the bootstrap token are logged with the special username ``<bootstrap>``, which is otherwise an invalid username.

.. _caching:

Caching
=======

In normal operation, Gafaelfawr often receives a flurry of identical authentication subrequests.
This can happen from requent API calls, but is even more common for users using a web browser, since each request for a resource from the service (images, JavaScript, icons, etc.) triggers another auth subrequest.
Gafaelfawr therefore must be able to answer those subrequests as quickly as possible, and should not pass that query load to backend data stores and other services that may not be able to handle that volume.

This is done via caching.
In most places where Gafaelfawr is described as retrieving information from another service, this is done through an in-memory cache.
Gafaelfawr also caches notebook and internal tokens for a specific token to avoid creating many new internal child tokens in short succession.

Gafaelfawr uses the following caches:

* Caches of mappings from parent token parameters to reusable child notebook tokens and internal tokens.
  The cache is designed to only return a token if it satisfies the criteria for :ref:`reuse of a notebook or internal token <token-reuse>`.
  Each of these caches holds up to 5,000 entries.
* Three caches of LDAP data if LDAP is enabled: group membership of a user (including GIDs), group membership of a user (only group names, used for scopes), and user identity information (name, email, and UID, whichever is configured to come from LDAP).
  Each of these caches holds up to 1,000 entries, and entries are cached for at most five minutes.
* Caches of mappings of users to UIDs and group names to GIDs, if Firestore is enabled.
  Each of these caches holds up to 10,000 entries.
  Since UIDs and GIDs are expected to never change once assigned, the cache entries never expire for the lifetime of the Gafaelfawr process.

All of these caches are only in memory in an individual Gafaelfawr pod.
Deployments that run multiple Gafaelfawr pods for availability and performance will therefore have separate memory caches per pod and somewhat more cache misses.

Locking
-------

Gafaelfawr is, like most internal Science Platform applications, a FastAPI Python app using Python's asyncio support.
All caches are protected by asyncio locks using the following sequence of operations:

#. Without holding a lock, ask the cache if it has the required data.
   If so, return it.
#. Acquire a lock on the cache.
#. Ask again if the cache has the required data, in case another thread of execution already created and stored the necessary data.
   If so, return it.
#. Make the external request, create the token, or otherwise acquire the data that needs to be cached.
   If this fails, release the lock without modifying the cache and throw the resulting exception.
#. Store the data in the cache.
#. Release the lock on the cache.

The caches of UIDs and GIDs use a simple single-level lock.
The LDAP and token caches use a more complicated locking scheme so that a thread of execution processing a request for one user doesn't interfere with a thread of execution processing a request for a different user.
That lock scheme works as follows:

#. Acquire a lock over a dictionary of users to locks.
#. Get the per-user lock if it already exists.
   If not, create a new lock for this user and store it in the lock dictionary.
#. Acquire the per-user lock.
#. Release the lock on the dictionary of users to locks.

The operation protected by the lock is then performed, and the per-user lock is released at the end of that operation.

Token API
=========

Token UI
--------

Implements IDM-0105.

The Science Platform provides a token management UI linked from the front page of each instance of the Science Platform.
That UI uses the user's session token for authentication and makes API calls to view tokens, create new user tokens, delete or modify tokens, or review token history.

Currently, the UI is implemented in React using Gatsby to package the web application, without any styling.
In the future, we expect to move it to Next.js and integrate it with the styles and visual look of the browser interface to the Science Platform.

.. _csrf:

CSRF protection
---------------

Rejected alternatives
---------------------

We considered serving the token UI using server-rendered HTML and a separate interface from the API, but decided against it for two reasons.
First, having all changes made through the API (whether by API calls or via JavaScript) ensures that the API always has parity with the UI, ensures that every operation can be done via an API, and avoids duplicating some frontend code.
Second, other Rubin-developed components of the Science Platform are using JavaScript with a common style dictionary to design APIs, so building the token UI using similar tools will make it easier to maintain a standard look and feel.

Specific services
=================

The general pattern for protecting a service with authentication and access control is configure its ``Ingress`` resources with the necessary ingress-nginx annotations and then let Gafaelfawr do the work.
If the service needs information about the user, it obtains that from the ``X-Auth-Request-*`` headers that are set by Gafaelfawr via ingress-nginx.
However, some Science Platform services require additional special attention.

Notebook Aspect
---------------

JupyterHub supports an external authentication provider, but then turns that authentication into an internal session that is used to authenticate and authorize subsequent actions by the user.
This session is normally represented by a cookie JupyterHub sets in the browser.
JupyterHub also supports bearer tokens, with the wrinkle that JupyterHub requires using the ``token`` keyword instead of ``bearer`` in the ``Authorization`` header.

JupyterHub then acts as an OAuth authentication provider to authenticate the user to any spawned lab.
The lab obtains an OAuth token for the user from the hub and uses that for subsequent authentication to the lab.

The JupyterHub authentication session can include state, which is stored in the JupyterHub session database.
In the current Science Platform implementation, that session database is stored in a PostgreSQL server also run inside the same Kubernetes cluster, protected by password authentication with a password injected into the JupyterHub pod.
The data stored in the authentication session is additionally encrypted with a key known only to JupyterHub.

The ingress for JupyterHub is configured to require Gafaelfawr authentication and access control for all JupyterHub and lab URLs.
Therefore, regardless of what JupyterHub and the lab think is the state of the user's authentication, the request is not allowed to reach them unless the user is already authenticated, and any redirects to the upstream identity provider are handled before JupyterHub ever receives a request.
The user is also automatically redirected to the upstream identity provider to reauthenticate if their credentials expire while using JupyterHub.
The ingress configuration requests a delegated notebook token.

Gafaelfawr is then integrated into JupyterHub with a custom JupyterHub authentication provider.
That provider runs inside the context of a request to JupyterHub that requires authentication.
It registers a custom route (``/gafaelfawr/login`` in the Hub's route namespace) and returns it as a login URL.
That custom route reads the headers from the incoming request, which are set by Gafaelfawr, to find the delegated notebook token, and makes an API call to Gafaelfawr using that token for authentication to obtain the user's identity information.
That identity information along with the token are then stored as the JupyterHub authentication session state.
Information from the authentication session state is used when spawning a user lab to control the user's UID, groups, and other information required by the lab, and the notebook token is injected into the lab so that it will be available to the user.

.. figure:: /_static/flow-jupyter.svg
   :name: JupyterHub and lab authentication flow

   Sequence diagram of the authentication flow between Gafaelfawr, JupyterHub, and the lab.
   This diagram assumes the user is already authenticated to Gafaelfawr and therefore omits the flow to the external identity provider (see :ref:`Browser flows <browser-flows>`).

Because JupyterHub has its own authentication session that has to be linked to the Gafaelfawr authentication session, there are a few wrinkles here that require special attention.

- When the user reauthenticates (because, for example, their credentials have expired), their JupyterHub session state needs to be refreshed even if JupyterHub thinks their existing session is still valid.
  Otherwise, JupyterHub will hold on to the old token and continue injecting it into labs, where it won't work and cause problems for the user.
  JupyterHub is therefore configured to force an authentication refresh before spawning a lab (which is when the token is injected), and the authentication refresh checks the delegated token provided in the request headers to see if it's the same token stored in the authentication state.
  If it is not, the authentication state is refreshed from the headers of the current request.

- The user's lab may make calls to JupyterHub on the user's behalf.
  Since the lab doesn't know anything about the Gafaelfawr token, those calls are authenticated using the lab's internal credentials.
  These must not be rejected by the authentication refresh logic, or the lab will not be allowed to talk to JupyterHub.

  Since all external JupyterHub routes are protected by Gafaelfawr and configured to provide a notebook token, the refresh header can check for the existence of an ``X-Auth-Request-Token`` header set by Gafaelfawr.
  If that header is not present, the refresh logic assumes that the request is internal and defers to JupyterHub's own authentication checks without also applying the Gafaelfawr authentication integration.

Note that this implementation approach depends on Gafaelfawr reusing an existing notebook token if one already exists.
Without that caching, there would be unnecessary churn of the JupyterHub authentication state.

The notebook token is only injected into the lab when the lab is spawned, so it's possible for the token in a long-running lab to expire.
If the user's overall Gafaelfawr session has expired, they will be forced to reauthenticate and their JupyterHub authentication state will then be updated via JupyterHub's authentication refresh, but the new stored token won't propagate automatically to the lab.
This is currently an open issue, worked around by setting a timeout on labs so that the user is forced to stop and restart the lab rather than keeping the same lab running indefinitely.

Portal Aspect
-------------

Similar to the Notebook Aspect, the Portal Aspect needs to make API calls on behalf of the user (most notably to the TAP and image API services).
Unlike the Notebook Aspect, the Portal Aspect uses a regular internal token with appropriate scopes for this.

In the Science-Platform-specific modifications to Firefly, the software used to create the Portal Aspect, that internal token is extracted from the ``X-Auth-Request-Token`` header and sent when appropriate in requests to other services.
Since the Portal Aspect supports using other public TAP and image services in addition to the ones local to the Science Platform deployment in which it's running, it has to know when to send this token in an ``Authorization`` header and when to omit it.
(We don't want to send the user's token to third-party services, since that's a breach of the user's credentials.)
Currently, this is done via a whitelist of domains in the Science Platform deployment configuration.
The Portal Aspect includes the token in all requests to those domains.

Remaining work
==============

The following portions of the described implementation are not yet complete.

- Force two-factor authentication for administrators (IDM-0007)
- Force reauthentication to provide an affiliation (IDM-0009)
- Changing usernames (IDM-0012)
- Handling duplicate email addresses (IDM-0013)
- Disallow authentication from pending or frozen accounts (IDM-0107)
- Logging of COmanage changes to users (IDM-0200)
- Logging of authentications via Kafka to the auth history table (IDM-0203)
- Authentication history per federated identity (IDM-0204)
- Last used time of user tokens (IDM-0205)
- Email notification of federated identity and user token changes (IDM-0206)
- Freezing accounts (IDM-1001)
- Deleting accounts (IDM-1002)
- Setting an expiration date on an account (IDM-1003, IDM-1301)
- Notifying users of upcoming account expiration (IDM-1004)
- Notifying users about email address changes (IDM-1101)
- User class markers (IDM-1103, IDM-1310)
- Quotas (IDM-1200, IDM-1201, IDM-1202, IDM-1203, IDM-1303, IDM-1401, IDM-1402, IDM-2100, IDM-2101, IDM-2102, IDM-2103, IDM-2201, IDM-3003)
- Administrator verification of email addresses (IDM-1302)
- User impersonation (IDM-1304, IDM-1305, IDM-2202)
- Review newly-created accounts (IDM-1309)
- Merging accounts (IDM-1311)
- Logging of administrative actions tagged appropriately (IDM-1400, IDM-1403, IDM-1404)
- Affiliation-based groups (IDM-2001)
- Group name restrictions (IDM-2004)
- Expiration of group membership (IDM-2005)
- Group renaming while preserving GID (IDM-2006)
- Correct handling of group deletion (IDM-2007)
- Groups owned by other groups (IDM-2009)
- Logging of group changes (IDM-2300, IDM-2301, IDM-2302, IDM-2303, IDM-2304, IDM-2305, IDM-4002)
- API to COmanage (IDM-3001)
- Scale testing (IDM-4000)
- Scaling of group membership (IDM-4001)

.. _references:

References
==========

Design
------

DMTN-225_
    Metadata gathered and stored for each user, including constraints such as valid username and group name patterns and UID and GID ranges.

DMTN-234_
    High-level design for the Rubin Science Platform identity management system.
    This is the document to read first to understand the overall system.

SQR-044_
    Requirements for the identity management system.
    This document is now incompete and partly out of date, but still provides useful detail of requirements that have not yet been incorporated into the design.

SQR-049_
    Detailed design of the token management system for the Science Platform, including its API and storage model.
    Not all of the elements of this design have been implemented, and some of them may be modified before implementation.

.. _DMTN-225: https://dmtn-225.lsst.io/
.. _DMTN-234: https://dmtn-225.lsst.io/
.. _SQR-044: https://sqr-044.lsst.io/
.. _SQR-049: https://sqr-049.lsst.io/

Security
--------

DMTN-193_
    General discussion of web security for the Science Platform, which among other topics suggests additional design considerations for the Science Platform ingress, authentication layer, and authorization layer.

SQR-051_
    Discussion of credential leaks from the authentication system to backend services, and possible fixes and mitigations.

.. _DMTN-193: https://dmtn-193.lsst.io/
.. _SQR-051: https://sqr-051.lsst.io/

Implementation details
----------------------

DMTN-235_
    Lists the token scopes used by the identity management system, defines them, and documents the services to which they grant access.

SQR-055_
    How to configure COmanage for the needs of the identity management component of the Science Platform.

.. _DMTN-235: https://dmtn-235.lsst.io/
.. _SQR-055: https://sqr-055.lsst.io/

Operations
----------

Gafaelfawr_
    The primary component of the identity management system.
    Its documentation convers operational issues such as configuration and maintenance.

Phalanx_
    The configuration and deployment infrastructure for the Science Platform.
    Its documentation includes operational details on how to configure services to correctly use the identity management system.

.. _Gafaelfawr: https://gafaelfawr.lsst.io/
.. _Phalanx: https://phalanx.lsst.io/

Project documents
-----------------

These are higher-level documents discussing Vera C. Rubin Observatory and the Science Platform as a whole that contain information relevant to the design and implementation of the identity management system.

LDM-554_
    General requirements document for the Science Platform.
    This includes some requirements for the identity management system.

LSE-279_
    General discussion of authentication and authorization for Vera C. Rubin Observatory.
    This is primarily a definition of terms and very high-level requirements for identity management.
    The group naming scheme described in this document has been replaced with the scheme in DMTN-235_.

LPM-121_
    Information security policy and procedures for Vera C. Rubin Observatory.
    This document is primarily concerned with defining roles and responsibilities.

RDO-013_
    The Vera C. Rubin Observatory Data Policy, which defines who will have access to Rubin Observatory data.

.. _LDM-554: https://ldm-554.lsst.io/
.. _LSE-279: https://docushare.lsst.org/docushare/dsweb/Get/LSE-279
.. _LPM-121: https://docushare.lsst.org/docushare/dsweb/Get/LPM-121
.. _RDO-013: https://docushare.lsst.org/docushare/dsweb/Get/RDO-13

Vendor evaluations
------------------

SQR-045_
    Evaluation of CILogon COmanage for use as the basis of user identity management and group management.

SQR-046_
    Evaluation of GitHub for use as the basis of user identity management and group management.

.. _SQR-045: https://sqr-045.lsst.io/
.. _SQR-046: https://sqr-046.lsst.io/

History
-------

DMTN-094_
    Original design document for the identity management system, now superseded and of historical interest only.

DMTN-116_
    Original implementation strategy for the identity management system, now superseded and of historical interest only.

SQR-039_
    Problem statement and proposed redesign for the identity management system.
    This document contains a detailed discussion of the decision not to use :abbr:`JWTs (JSON Web Tokens)` in the authentication system, and to keep authorization information such as group credentials out of the authentication tokens.

SQR-069_
    Documents the decisions, trade-offs, and analysis behind the current design and implementation of the identity management system.

.. _DMTN-094: https://dmtn-094.lsst.io/
.. _DMTN-116: https://dmtn-116.lsst.io/
.. _SQR-039: https://sqr-039.lsst.io/
.. _SQR-069: https://sqr-069.lsst.io/
