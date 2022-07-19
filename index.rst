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

Restricted access deployments use either GitHub or a local OpenID Connect authentication provider as the source of user authentication; and one of GitHub, a local LDAP server, or the OpenID Connect authentication provider as the source of identity information.

A restricted access deployment that uses GitHub looks essentially identical to the first architecture diagram with GitHub as the identity provider.
One that uses OpenID Connect is similar, but will likely separate the identity provider box into an OpenID Connect provider and an LDAP server that will be queried for metadata.

Identity management
===================

The identity management component of the system authenticates the user and maps that authentication to identity information.

In general access deployments, authentication is done via the OpenID Connect protocol using CILogon, which in turn supports SAML and identity federations as well as other identity providers such as GitHub and Google.
Restricted access deployments use either an OAuth 2.0 authentication request to GitHub or an OpenID Connect authentication request to a local identity provider.

Once the user has been authenticated, their identity must be associated with additional information: full name, email address, numeric UID, group membership, and numeric GIDs for the groups.
In general access deployments, most of this data comes from :ref:`COmanage <comanage>` (via LDAP), and numeric UIDs and GIDs come from :ref:`Firestore <firestore>`.
For restricted access deployments using GitHub, access to the user's profile and organization membership is requested as part of the OAuth 2.0 request, and then retrieved after authentication with the token obtained by the OAuth 2.0 authentication.  See :ref:`GitHub <github>` for more details.
With OpenID Connect, this information is either extracted from the claims of the JWT_ issued as a result of the OpenID Connect authentication flow, or is retrieved from LDAP.

.. _JWT: https://datatracker.ietf.org/doc/html/rfc7519

See DMTN-225_ for more details on the identity information stored for each user and its sources.

.. _comanage:

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
Otherwise, Gafaelfawr retrieves group information from LDAP and then uses that to assign scopes to the newly-created session token (see :ref:`Login flows <login-flows>`).

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

If the user has authenticated with GitHub, the token returned to the OAuth App by GitHub is stored in the user's encrypted cookie.
When the user logs out, that token is used to explicitly revoke the user's OAuth App authorization at GitHub.
This forces the user to return to the OAuth App authorization screen when logging back in, which in turn will cause GitHub to release any new or changed organization information.
Without the explicit revocation, GitHub reuses the prior authorization with the organization and team data current at that time and doesn't provide data from new organizations.
See :ref:`Cookie data <cookie-data>` for more information.

Authentication flows
====================

For general access environments that use COmanage, this section assumes the COmanage account for the user already exists.
If it does not, see :ref:`COmanage onboarding <comanage-onboarding>`.

Browser flow
------------

Implements IDM-0001 and IDM-0200.

If the user visits a Science Platform page intended for a web browser (as opposed to APIs) and is not already authenticated (either missing a cookie or having an expired cookie), they will be sent to an appropriate authentication provider.
This normally uses the `OpenID Connect`_ protocol.
(Authentications to GitHub instead use GitHub's OAuth 2.0 protocol instead.)

.. _OpenID Connect: https://openid.net/specs/openid-connect-core-1_0.html

Three different authentication providers are supported:

- GitHub_
- CILogon_
- Generic OpenID Connect support

.. _GitHub: https://docs.github.com/en/developers/apps/building-oauth-apps/authorizing-oauth-apps

In all cases, the authentication flow first redirects the user's web browser to the authentication provider (which in the case of CILogon may be multiple hops, first to CILogon and then to the underlying federated identity provider).
The user authenticates there.
Then, the browser is redirected back to the Science Platform with an authentication code, which is redeemed for credentials from the upstream authentication provider and then used to retrieve metadata about the user.
That data, in turn, is used to create a new token, which is stored in the user's cookies for the Science Platform.
This token is called a "session" token.

The authentication cookie is marked ``Secure`` and ``HttpOnly`` and is encrypted in a private key of that Science Platform instance (IDM-0008).

The data gathered for each user, and its sources, are detailed in DMTN-225_.

Token scopes
------------

Implements IDM-0104.

Each token is associated with a list of scopes.
Those scopes are used to control access to components of the Science Platform.
The scopes of a user's session token are determined from their group memberships at the point when the session token is created and a mapping from groups to scopes maintained in the Science Platform configuration.
The scopes then do not change for the lifetime of the token.

Tokens for that user created via their session token (such as :ref:`user tokens <user-tokens>` and :ref:`internal tokens <internal-tokens>`) have a subset of the scopes of the session token.
In some cases, that may be the same list of scopes, but in most cases, it will be a proper subset.

.. _user-tokens:

User token flow
---------------

Implements IDM-0202.

Users can create their own tokens and manage them via a web UI.
Such a token can be provided via an ``Authorization`` header to authenticate to Science Platform APIs via programs or other non-browser applications.
These tokens are called "user" tokens and are given a unique token name by the user on creation (which can be changed later).

The metadata about the user associated with their user tokens is the same as that associated with the session token used to create the user token.
User tokens can be limited 

See SQR-049_ for a detailed description of user tokens and the APIs used to manage them.
This system implements IDM-0100, IDM-0102, IDM-1307, and IDM-3000.

These tokens cannot be used to access COmanage or change any of the information stored there (IDM-0101).

.. _internal-tokens:

Internal tokens
---------------

Implements IDM-0103.

Bearer tokens, either in ``Authorization`` headers or in cookies, are used for all internal authentication insice the Science Platform.
Many Science Platform components will need authentication credentials for the user to act on their behalf when talking to another service.
For example, the Portal Aspect will need to make TAP queries on the user's behalf.
However, the Portal Aspect should not have unrestricted access to authenticate as the user, only restricted access to the services that it needs to talk to.
For example, the Portal Aspect should not be able to create a notebook as the user in the Notebook Aspect.

This is done with "internal" tokens, which are created as needed and passed to services that need delegated access.
These tokens have the same or shorter expiration time as the original token used to authenticate to the first service, and are automatically deleted when that token is deleted.
They are restricted to the scopes required by the service.

Usernames
---------

When using either GitHub or the generic OpenID Connect support, the username of a user within the Science Platform will match the username asserted by GitHub or the OpenID Connect provider.

When using CILogon, there is an additional level of indirection.
Because CILogon supports federated identity, it does not itself guarantee unique usernames or necessarily map an authenticated user to a username.
Instead, CILogon provides a unique identity URI (for example, ``http://cilogon.org/serverA/users/31388556``).

The mapping of that identity to a username is handled in :ref:`COmanage <comanage-auth>`.
That information is exposed to the Science Platform via LDAP.
To determine the username of a newly-authenticated user, the Science Platform therefore does an LDAP lookup for a record with a ``voPersonSoRID`` matching the CILogon identity URI in the ``sub`` claim of the JWT.
The ``uid`` attribute is the username for Science Platform purposes.

User metadata in tokens
-----------------------

Implements IDM-1100.

All Gafaelfawr authentication is done via tokens, optionally encoded inside a browser cookie.
That token has associated data stored in Redis and possibly in a PostgreSQL database.
Some data is associated with every token regardless of the identity management system.
(See SQR-049_ for all the details.)
Four pieces of data may be stored with the token or may be retrieved on the fly, depending on the identity management system:

- Full name
- Email address
- Numeric UID
- Group membership (group names and GIDs)

When GitHub or a generic OpenID Connect provider are used as the upstream source of identity information, this information is determined during initial authentication and stored with the token.
That information is then fixed for the lifetime of the token and will not reflect any changes in the upstream sources of data.

When CILogon and COmanage are used, this information is not stored with the token.
Instead, whenever that information is needed, it is retrieved from the COmanage LDAP server, or from a local cache of LDAP results whose lifetime should not exceed five minutes (IDM-0106, IDM-3002).

In either case, the same API is used to retrieve the user metadata, and user metadata is passed via the same HTTP headers, all of which are described in SQR-049_.

Storage
=======

.. _cookie-data:

Cookie data
-----------

Token UI
========

Implements IDM-0105.

The Science Platform provides a token management UI linked from the front page of each instance of the Science Platform.
That UI uses the user's session token for authentication and makes API calls to view tokens, create new user tokens, delete or modify tokens, or review token history.

Currently, the UI is implemented in React using Gatsby to package the web application, without any styling.
In the future, we expect to move it to Next.js and integrate it with the styles and visual look of the browser interface to the Science Platform.

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
   This diagram assumes the user is already authenticated to Gafaelfawr and therefore omits the flow to the external identity provider (covered in earlier flow diagrams).

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
