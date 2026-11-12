import type { TextKey } from "./en";

/**
 * Les textes de la page en français. Espaces insécables avant « : ; ? ! »
 * et à l'intérieur des guillemets, comme le veut l'usage.
 */
export const fr: Record<TextKey, string> = {
  "app.skipToContent": "Aller au contenu",
  "nav.main": "Navigation principale",
  "nav.dashboard": "Tableau de bord",
  "nav.files": "Fichiers",
  "title.dashboard": "Tableau de bord",
  "title.files": "Fichiers",
  "title.notFound": "Page introuvable",
  "title.signIn": "Connexion",
  "title.choosePassword": "Choisir un mot de passe",
  "title.settings": "Réglages",
  "nav.settings": "Réglages",

  "access.checking": "Ouverture de Mariner…",
  "signIn.heading": "Connexion à Mariner",
  "signIn.password": "Mot de passe",
  "signIn.submit": "Se connecter",
  "signIn.submitting": "Connexion…",
  "signIn.lost":
    "Mot de passe perdu\u00a0? Sur l'ordinateur qui fait tourner Mariner, lancez «\u00a0sudo mariner reset-password\u00a0», ou déposez un fichier vide nommé «\u00a0reset-password\u00a0» sur la partition de démarrage de sa carte puis redémarrez-le. Un nouveau mot de passe se choisit alors ici.",
  "choose.heading": "Choisir un mot de passe",
  "choose.intro":
    "Il sera demandé à toute personne qui ouvre cette page. Les trancheurs (UVtools, ChiTuBox) envoient leurs fichiers sans lui\u00a0: leur accès se coupe dans les réglages.",
  "choose.new": "Nouveau mot de passe",
  "choose.hint": "Au moins 8 caractères.",
  "choose.repeat": "Répéter le mot de passe",
  "choose.submit": "Enregistrer le mot de passe",
  "choose.submitting": "Enregistrement…",
  "choose.mismatch": "Les deux mots de passe ne sont pas identiques.",

  "settings.heading": "Réglages",
  "settings.loading": "Lecture des réglages…",
  "settings.loadError": "Les réglages n'ont pas pu être lus",
  "settings.saved": "Enregistré",
  "settings.printer": "Imprimante",
  "settings.name": "Nom affiché pour l'imprimante",
  "settings.name.hint":
    "Affiché sur le tableau de bord. Laissez vide pour reprendre le nom du fichier de configuration.",
  "settings.name.save": "Enregistrer le nom",
  "settings.slicers": "Trancheurs",
  "settings.slicers.intro":
    "Les trancheurs envoient des fichiers et lancent des impressions par le réseau sans le mot de passe\u00a0: ils ne savent pas en donner. Coupez ce que vous n'utilisez pas.",
  "settings.uvtools": "UVtools",
  "settings.uvtools.hint":
    "Fichiers et commandes envoyés par UVtools, sur le port de cette page.",
  "settings.sdcp": "ChiTuBox (SDCP)",
  "settings.sdcp.hint":
    "L'impression en réseau que parle ChiTuBox\u00a0: découverte, fichiers et commandes sur les ports 3000 et 3030.",
  "settings.files": "Fichiers",
  "settings.assumeOff": "Ne pas demander quand l'imprimante ne répond pas",
  "settings.assumeOff.hint":
    "Remplacer ou supprimer un fichier se fait alors sans question quand l'imprimante est muette, comme si vous aviez confirmé qu'elle est éteinte. Un fichier en cours d'impression reste protégé quand l'imprimante répond.",
  "settings.restartNeeded":
    "Ce changement prendra effet au prochain démarrage de Mariner.",
  "settings.restartByHand":
    "Redémarrez Mariner de la façon dont il a été lancé pour qu'il prenne effet.",
  "settings.restart": "Redémarrer Mariner",
  "settings.restarting": "Redémarrage…",
  "settings.restarted": "Mariner redémarre. Cette page revient toute seule.",
  "settings.password": "Mot de passe",
  "settings.password.current": "Mot de passe actuel",
  "settings.password.repeat": "Répéter le nouveau mot de passe",
  "settings.password.change": "Changer le mot de passe",
  "settings.password.changed":
    "Mot de passe changé. Les autres pages ont été déconnectées.",
  "settings.signOut": "Se déconnecter",

  "appearance.open": "Apparence",
  "appearance.theme": "Thème de couleurs",
  "appearance.typeface": "Police de caractères",
  "appearance.language": "Langue",
  "font.hyperlegible.hint": "Des lettres dessinées pour ne pas se confondre",
  "font.opendyslexic.hint":
    "Des lettres lestées, pour les lecteurs dyslexiques",

  "power.open": "Éteindre ou redémarrer",
  "power.heading": "Ordinateur qui fait tourner Mariner",
  "power.reboot": "Redémarrer",
  "power.rebootConfirm": "Confirmer le redémarrage ?",
  "power.shutdown": "Éteindre",
  "power.shutdownConfirm": "Confirmer l'arrêt ?",
  "power.rebootAgain": "Appuyez de nouveau pour redémarrer l'ordinateur.",
  "power.shutdownAgain": "Appuyez de nouveau pour éteindre l'ordinateur.",
  "power.rebooting": "L'ordinateur redémarre. Cette page revient toute seule.",
  "power.shuttingDown": "L'ordinateur s'éteint.",
  "power.rebootAsking": "Redémarrage…",
  "power.shutdownAsking": "Arrêt…",
  "power.noAnswer":
    "Mariner n'a pas répondu\u00a0: l'ordinateur est peut-être en train de s'arrêter, ou n'a peut-être pas reçu la demande. Vérifiez avant de le débrancher.",

  "status.idle": "Prête",
  "status.printing": "Impression en cours",
  "status.paused": "En pause",
  "status.offline": "Hors ligne",
  "status.label": "Imprimante : {status}",

  "dashboard.heading": "Tableau de bord de l'imprimante",
  "dashboard.connecting": "Connexion à l'imprimante…",
  "dashboard.unreachable.title": "Mariner est injoignable",
  "dashboard.unreachable.text":
    "Vérifiez que l'ordinateur qui fait tourner Mariner est allumé et relié au réseau. Cette page réessaie toute seule.",
  "dashboard.idle.title": "Prête à imprimer",
  "dashboard.idle.text":
    "Choisissez un fichier dans la page Fichiers pour lancer une impression.",
  "dashboard.idle.open": "Voir les fichiers",
  "dashboard.offline.title": "L'imprimante ne répond pas",
  "dashboard.offline.text":
    "Vérifiez que l'imprimante est allumée et que son câble vers l'ordinateur qui fait tourner Mariner est branché.",

  "print.progress": "Avancement de l'impression",
  "print.currentLayer": "Couche en cours",
  "print.totalLayers": "Nombre de couches",
  "print.elapsed": "Écoulé (estimation)",
  "print.remaining": "Restant (estimation)",
  "print.file": "Fichier en cours d'impression",
  "print.pause": "Mettre en pause",
  "print.resume": "Reprendre",
  "print.cancel": "Annuler l'impression",
  "print.pausing": "Mise en pause…",
  "print.resuming": "Reprise…",
  "print.cancelling": "Annulation…",
  "print.cancel.title": "Annuler cette impression ?",
  "print.cancel.text":
    "{file} est imprimé à {progress}. Une impression annulée ne peut pas être reprise : il faut la relancer depuis la première couche.",
  "print.cancel.textNoFile":
    "Cette impression est faite à {progress}. Une impression annulée ne peut pas être reprise\u00a0: il faut la relancer depuis la première couche.",
  "print.cancel.keep": "Ne pas annuler",
  "print.cancel.confirm": "Annuler l'impression",
  "print.paused": "Impression en pause",
  "print.resumed": "Impression reprise",
  "print.cancelled": "Impression annulée",
  "print.started": "Impression lancée",

  "files.heading": "Fichiers",
  "files.folder": "Dossier : {path}",
  "files.newFolder": "Nouveau dossier",
  "files.upload": "Envoyer un fichier",
  "files.uploading": "Envoi de {file} : {percent}",
  "files.finishing": "Fin de l'envoi de {file}…",
  "files.uploadProgress": "Avancement de l'envoi",
  "files.uploadRegion": "Fichier en cours d'envoi",
  "files.uploaded": "{file} envoyé",
  "files.uploadCancel": "Annuler l'envoi",
  "files.uploadCancelled": "Envoi annulé",
  "files.loading": "Chargement des fichiers…",
  "files.error.title": "Impossible d'afficher les fichiers",
  "files.error.retry": "Réessayer",
  "files.empty": "Ce dossier est vide.",
  "files.up": "Remonter au dossier parent",
  "files.openFolder": "Ouvrir le dossier {name}",
  "files.printable": "Imprimable",
  "files.printTime": "Durée d'impression : {time}",
  "files.newFolder.in": "Créer un dossier dans {path}.",
  "files.newFolder.name": "Nom du dossier",
  "files.newFolder.create": "Créer",
  "files.newFolder.creating": "Création…",
  "files.newFolder.created": "Dossier créé",

  "file.details.printable": "Détails d'un fichier imprimable",
  "file.details.other": "Détails d'un fichier",
  "file.preview": "Aperçu de l'impression",
  "file.layers": "Couches",
  "file.time": "Durée d'impression",
  "file.height": "Hauteur",
  "file.delete": "Supprimer",
  "file.deleting": "Suppression…",
  "file.print": "Lancer l'impression",
  "file.starting": "Lancement…",
  "file.delete.title": "Supprimer ce fichier ?",
  "file.delete.text": "{file} sera supprimé définitivement.",
  "file.delete.confirm": "Supprimer le fichier",
  "file.deleted": "{file} supprimé",

  "printerOff.title": "L'imprimante ne répond pas",
  "printerOff.text":
    "Ne continuez que si l'imprimante est éteinte. Si elle est en train d'imprimer ce fichier, l'impression sera perdue.",
  "printerOff.replace": "Remplacer quand même",
  "printerOff.delete": "Supprimer quand même",

  "common.cancel": "Annuler",
  "common.close": "Fermer",
  "toasts.region": "Messages",

  "notFound.heading": "Page introuvable",
  "notFound.text": "Il n'y a rien à cette adresse.",
  "notFound.home": "Retour au tableau de bord",

  "error.network":
    "Mariner est injoignable. Vérifiez que l'ordinateur qui le fait tourner est allumé et relié au réseau.",
  "error.unknown": "Une erreur s'est produite (erreur {status}).",
  "error.wrong_password": "Ce n'est pas le mot de passe.",
  "error.too_many_attempts":
    "Trop de mots de passe erronés. Patientez un instant puis réessayez.",
  "error.password_too_short": "Un mot de passe compte au moins 8 caractères.",
  "error.password_too_long": "Un mot de passe compte au plus 1024 caractères.",
  "error.password_missing": "Aucun mot de passe n'a été donné.",
  "error.password_already_set":
    "Un mot de passe a déjà été choisi. Rechargez la page et connectez-vous.",
  "error.password_not_set":
    "Aucun mot de passe n'a encore été choisi. Rechargez la page pour en choisir un.",
  "error.login_required": "Connectez-vous d'abord.",
  "error.setting_not_valid": "Ce réglage n'a pas été pris en compte.",
  "error.restart_not_available":
    "Mariner ne tourne pas ici comme un service\u00a0: redémarrez-le de la façon dont il a été lancé.",
  "error.token_refused":
    "Cette page n'est plus à jour. Rechargez-la et réessayez.",
  "error.file_too_large": "Ce fichier dépasse la taille que Mariner accepte.",
  "error.request_too_large":
    "Cette demande dépasse la taille que Mariner accepte.",
  "error.upload_not_stored":
    "Il n'y a pas assez de place pour enregistrer ce fichier. Libérez de la place et envoyez-le de nouveau.",
  "error.folder_too_deep":
    "Les dossiers ne peuvent pas être imbriqués plus profondément.",
  "error.folder_exists": "Un dossier ou un fichier porte déjà ce nom.",
  "error.name_not_allowed":
    'Ce nom ne peut pas être utilisé. Évitez les apostrophes, les barres obliques et ces caractères\u00a0: \\\u00a0:\u00a0*\u00a0?\u00a0"\u00a0<\u00a0>\u00a0|\u00a0; ne le terminez pas par un point, et restez sous 255\u00a0caractères.',
  "error.name_is_a_folder":
    "Un dossier porte déjà ce nom\u00a0: un fichier ne peut pas prendre sa place.",
  "error.upload_unanswered":
    "Mariner n'a pas répondu après l'envoi du fichier. Regardez la liste\u00a0: le fichier y est peut-être.",
  "error.type_not_supported":
    "Ce n'est pas un fichier que l'imprimante sait imprimer. Mariner accepte\u00a0: {kinds}.",
  "error.folder_gone":
    "Ce dossier n'est plus là\u00a0: il a été supprimé ou renommé depuis l'affichage de la liste.",
  "error.file_gone":
    "Ce fichier n'est plus là\u00a0: il a été supprimé ou renommé depuis l'affichage de la liste.",
  "error.folder_not_created":
    "Le dossier n'a pas pu être créé\u00a0: son nom est peut-être trop long, ou le disque plein.",
  "error.printer_not_answering":
    "L'imprimante n'a pas répondu\u00a0: impossible de savoir si ce fichier est en cours d'impression. Il n'a pas été modifié.",
  "error.printer_answer_unclear":
    "Mariner n'a pas obtenu de réponse claire de l'imprimante\u00a0: ce fichier n'a pas été modifié. Réessayez dans un instant.",
  "error.host_command_refused":
    "L'ordinateur qui fait tourner Mariner n'a pas accepté la commande.",
  "error.print_in_progress":
    "L'imprimante imprime déjà. Attendez la fin de l'impression ou annulez-la d'abord.",
  "error.print_just_started":
    "Une impression vient d'être lancée. Les fichiers sont protégés pendant une demi-minute après un lancement, même si l'impression a été annulée. Réessayez dans un instant.",
  "error.file_in_use":
    "Ce fichier est en cours d'impression\u00a0: il ne peut pas être modifié avant la fin de l'impression.",
  "error.print_file_unknown":
    "L'imprimante imprime mais n'indique pas quel fichier\u00a0: celui-ci n'a pas été modifié. Réessayez dans un instant.",
  "error.browser_not_served":
    "Cette adresse est réservée aux logiciels de découpe (slicers), pas à un navigateur web.",
  "error.printer_error":
    "L'imprimante n'a pas accepté la commande. Vérifiez qu'elle est allumée et que son câble est branché.",
  "error.file_unreadable":
    "Ce fichier ne peut pas être lu comme un fichier à imprimer.",
  "error.file_read_failed": "Ce fichier n'a pas pu être lu sur le disque.",
  "error.internal_error":
    "Mariner a rencontré une erreur. Son journal en dit plus.",
  "error.cross_site_request":
    "Mariner a refusé cette demande car elle semble venir d'un autre site.",
  "error.host_not_allowed":
    "Mariner ne répond pas au nom sous lequel cette page a été ouverte.",
};
