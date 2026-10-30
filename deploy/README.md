# Deployment templates

Ready-made files for app stores and hosting platforms. Each runs the published image,
`ghcr.io/jasp-nerd/vinted-bot`, with its database on a persistent volume at `/data`.
For a plain Docker host, use the [docker-compose.yml](../docker-compose.yml) in the root.

| Folder | For | How it gets used |
|---|---|---|
| [unraid/](unraid/) | Unraid Community Applications | Submitted to CA (below), or added by hand |
| [umbrel/](umbrel/) | Umbrel community app store | Copied into a store repository |
| [casaos/](casaos/) | CasaOS and ZimaOS | Imported through Custom Install |
| [render/](render/) | Render | Blueprint, paid instance |
| [coolify/](coolify/) | Coolify | Docker Compose resource or template PR |

Two things are true everywhere:

- **The image fixes its own folder permissions.** Set `PUID` and `PGID` to whoever owns the
  data folder on the host and the container hands `/data` to that user before starting.
  The app never runs as root.
- **Anything reachable beyond the machine itself needs a password.** On a home NAS, set
  one in the dashboard's Settings before opening the port wider; on a host reachable from
  the internet, set `VINTED_BOT_WEB_AUTH_TOKEN` so it is locked from the first request.
  The dashboard shows your webhook links.

## Unraid

[unraid/vinted-bot.xml](unraid/vinted-bot.xml) is a Community Applications template.

To use it before it is listed: Docker tab, Add Container, paste the raw URL of the XML into
Template, and apply. To get it listed, Community Applications wants a repository with
`ca_profile.xml` at its root and one XML per app, so:

1. Create a repository such as `jasp-nerd/unraid-templates`, from
   [unraid/unraid-community-apps-starter](https://github.com/unraid/unraid-community-apps-starter).
2. Copy [unraid/ca_profile.xml](unraid/ca_profile.xml) to its root and the template into
   `templates/`, and point `TemplateURL` at the template's raw URL in that repository.
3. Sign in at [ca.unraid.net/submit](https://ca.unraid.net/submit), add the repository, then
   run Validate and Scan.

Unraid's own defaults, PUID 99 and PGID 100, are already filled in.

## Umbrel

[umbrel/](umbrel/) is laid out as a community app store: `umbrel-app-store.yml` at the root
and one folder per app whose name starts with the store id (`jasp-`). Copy it into a new
repository made from
[getumbrel/umbrel-community-app-store](https://github.com/getumbrel/umbrel-community-app-store),
then in Umbrel: App Store, the three dots, Community App Stores, and paste the repository URL.

Before each store update, set the image in `jasp-vinted-bot/docker-compose.yml` to the
release tag and its digest, and bump `version` in `umbrel-app.yml` to match. Umbrel puts its
own sign-in in front of the app, so no dashboard password is needed there.

Getting into the official store is a pull request to
[getumbrel/umbrel-apps](https://github.com/getumbrel/umbrel-apps) with the same two files
(without the `jasp-` prefix), reviewed by the Umbrel team.

## CasaOS and ZimaOS

In the CasaOS dashboard: App Store, Custom Install, the import button at the top right, and
paste [casaos/docker-compose.yml](casaos/docker-compose.yml). Uncomment the password line
first. The `x-casaos` block is the metadata community stores such as
[BigBear's](https://github.com/bigbeartechworld/big-bear-casaos) expect, so the same file is
the start of a pull request there (as `Apps/vinted-bot/docker-compose.yml` with a
`config.json` beside it).

## Synology

DSM 7.2 and later: Container Manager, Project, Create. Point it at a new folder, choose
"Create docker-compose.yml" and paste the [root compose file](../docker-compose.yml). Then
change two things:

- swap the named volume for `./data:/data`, so the database sits in the project folder;
- uncomment `PUID` and `PGID` and set them to your DSM user. Over SSH, `id` prints them;
  usually 1026 and 100.

## Portainer

Stacks, Add stack, Repository: `https://github.com/jasp-nerd/vinted-bot`, compose path
`docker-compose.yml`. Or Web editor and paste the file. Turn on "Re-pull image" when
updating.

## Render

[render/render.yaml](render/render.yaml) is a Blueprint. In Render: New, Blueprint, connect
your fork of this repository and set Blueprint Path to `deploy/render/render.yaml`. It is
paid only: a persistent disk needs a paid instance. Render generates the dashboard password;
it is under Environment.

## Coolify

[coolify/vinted-bot.yaml](coolify/vinted-bot.yaml) follows Coolify's service template
format: Coolify generates the dashboard password and the public URL. Paste it as a new
Docker Compose resource, or submit it to `templates/compose/` in
[coollabsio/coolify](https://github.com/coollabsio/coolify) with an icon in `svgs/`.

## Railway

Railway templates are made in its web interface rather than from a file:

1. New project, Deploy a Docker image: `ghcr.io/jasp-nerd/vinted-bot:latest`.
2. Add a volume mounted at `/data`.
3. Variables: `VINTED_BOT_WEB_AUTH_TOKEN` set to a long random value (the template
   editor can generate one), `VINTED_BOT_WEB_PUBLIC_URL` set to
   `https://${{RAILWAY_PUBLIC_DOMAIN}}`, and `TZ`.
4. Networking: generate a domain on port 8000.
5. Publish it as a template to get a Deploy on Railway button.

## Before paying for any cloud host

Vinted refuses some datacenter addresses. Run the check in
[troubleshooting](../docs/troubleshooting.md#vinted-reachable-from-this-machine) from the
host, or look at the dashboard after the first start, before you commit to a plan.
